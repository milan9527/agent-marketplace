from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.auth import current_user
from app.db import session_factory
from app.main import app
from app.models import Agent, Bid, Event, Task, User
from app.seed import seed_catalog


def create(client, **extra):
    response = client.post(
        "/api/tasks",
        json={
            "title": "Compare developer products",
            "spec": "Research developer product positioning from the supplied information.",
            "category": "Research",
            "budget": "0.05",
            "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return "/api/tasks/" + response.json()["id"]


def test_auto_mode_chooses_eligible_value_without_payment(client, monkeypatch):
    with session_factory()() as db:
        seed_catalog(db)
        db.get(Agent, "demo-atlas").reputation_total = 5
        db.get(Agent, "demo-atlas").reputation_count = 1
        db.commit()

    def evaluate(payload):
        return {
            "bids": [
                {
                    "agent_id": a["id"],
                    "match_score": 95 if a["id"] == "demo-atlas" else 65,
                    "rationale": "Supplied skills assessment",
                }
                for a in payload["agents"]
            ]
        }

    monkeypatch.setattr("app.service.call_bidders", evaluate)
    url = create(client, selection_mode="auto", agent_scope="demo")
    response = client.post(url + "/quote")
    assert response.status_code == 200
    task = response.json()
    assert task["status"] == "demo_ready" and task["winner_id"] == "demo-atlas"
    assert task["selection_mode"] == "auto"
    assert "highest quality × match / price" in task["selection_reason"]
    assert all(b["agent"]["is_demo"] for b in task["bids"])
    assert task["payment"] is None
    assert client.get("/api/payments").json() == []
    assert client.get("/api/me").json()["spent"] == "0.000000"
    assert client.post(url + "/auto-select").json()["winner_id"] == "demo-atlas"
    assert client.post(url + "/quote").json()["winner_id"] == "demo-atlas"
    with session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Event)
                .where(Event.task_id == task["id"], Event.kind == "winner_selected")
            )
            == 1
        )


def test_manual_task_can_auto_select_and_paid_agent_still_requires_payment(client):
    url = create(client, agent_scope="live")
    quoted = client.post(url + "/quote").json()
    assert quoted["status"] == "bidding" and quoted["winner_id"] is None
    assert quoted["selection_mode"] == "manual"
    assert quoted["recommended_bid_id"]
    selected = client.post(url + "/auto-select").json()
    assert selected["status"] == "awaiting_payment"
    assert selected["selection_mode"] == "auto"
    assert selected["payment"] is None
    assert client.post(url + "/deliver").status_code == 409
    assert client.get("/api/payments").json() == []
    assert client.get(url).json()["selection_reason"] == selected["selection_reason"]


def test_no_suitable_auto_bid_leaves_manual_choice_and_budget_enforced(client):
    url = create(client, selection_mode="auto", preferred_agent_id="codecraft")
    task = client.post(url + "/quote").json()
    assert task["status"] == "bidding"
    assert task["winner_id"] is None and task["recommended_bid_id"] is None
    assert "70%" in task["selection_reason"]
    manual = client.post(url + "/select", json={"bid_id": task["bids"][0]["id"]}).json()
    assert manual["selection_mode"] == "manual"
    assert manual["status"] == "awaiting_payment"
    over_budget = create(client, selection_mode="auto", budget="0.000001")
    result = client.post(over_budget + "/quote").json()
    assert result["status"] == "bidding" and result["winner_id"] is None
    assert client.post(over_budget + "/auto-select").json()["winner_id"] is None
    assert (
        client.post(
            over_budget + "/select", json={"bid_id": result["bids"][0]["id"]}
        ).status_code
        == 422
    )


def test_auto_select_excludes_inactive_agents_and_breaks_ties_deterministically(client):
    url = create(client)
    client.post(url + "/quote")
    with session_factory()() as db:
        bids = db.scalars(
            select(Bid).where(Bid.task_id == url.rsplit("/", 1)[-1])
        ).all()
        for bid in bids:
            bid.match_score, bid.quality_score, bid.price_micros = 90, 80, 20000
        db.get(Agent, "atlas").active = False
        db.commit()
    result = client.post(url + "/auto-select").json()
    assert result["winner_id"] == "codecraft"


def test_concurrent_manual_and_auto_selection_records_one_winner(client):
    url = create(client)
    task = client.post(url + "/quote").json()
    bid = task["bids"][0]
    with ThreadPoolExecutor(max_workers=2) as executor:
        calls = [
            executor.submit(client.post, url + "/auto-select"),
            executor.submit(client.post, url + "/select", json={"bid_id": bid["id"]}),
        ]
        results = [call.result() for call in calls]
    assert all(r.status_code in (200, 409) for r in results)
    with session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Event)
                .where(Event.task_id == task["id"], Event.kind == "winner_selected")
            )
            == 1
        )
    assert client.get("/api/payments").json() == []


def test_auto_selection_owner_deadline_and_scope_are_enforced(client):
    no_demo = create(client, agent_scope="demo")
    assert client.post(no_demo + "/quote").status_code == 409
    assert client.get(no_demo).json()["status"] == "open"
    url = create(client)
    client.post(url + "/quote")
    with session_factory()() as db:
        task = db.get(Task, url.rsplit("/", 1)[-1])
        task.deadline = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        db.add(User(id="someone-else", name="Another user"))
        db.commit()
    assert client.post(url + "/auto-select").status_code == 409
    app.dependency_overrides[current_user] = lambda: User(id="someone-else")
    assert client.post(url + "/auto-select").status_code == 404


def test_aws_bids_never_invent_matches_for_omitted_agents(monkeypatch):
    from app.agents import run_bidders

    monkeypatch.setattr(
        "app.agents.get_settings", lambda: SimpleNamespace(app_mode="aws")
    )
    monkeypatch.setattr(
        "app.execution.plan_task",
        lambda _: {
            "web": False,
            "code": False,
            "external_actions": [],
            "missing_inputs": [],
        },
    )
    monkeypatch.setattr(
        "app.agents.converse_structured",
        lambda *_: {
            "bids": [
                {"agent_id": "a", "match_score": 80, "rationale": "Relevant skills."}
            ]
        },
    )
    payload = {
        "action": "quote",
        "task": {"category": "Research"},
        "agents": [
            {"id": "a", "category": "Research", "skills": ["research"]},
            {"id": "omitted", "category": "Research", "skills": ["research"]},
        ],
    }
    assert [b["agent_id"] for b in run_bidders(payload)["bids"]] == ["a"]
    for invalid in (
        [],
        [{"agent_id": "a", "match_score": 101, "rationale": "Invalid"}],
        [{"agent_id": "a", "match_score": "95", "rationale": "Invalid"}],
    ):
        monkeypatch.setattr(
            "app.agents.converse_structured", lambda *_, bids=invalid: {"bids": bids}
        )
        with pytest.raises(ValueError):
            run_bidders(payload)
