from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.auth import current_user
from app.config import get_settings
from app.db import session_factory
from app.main import app
from app.models import Payment, User


def task_body(title):
    return {
        "title": title,
        "spec": "Compare the supplied business scenarios and explain the tradeoffs.",
        "category": "Research",
        "budget": "1.00",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }


def sign_in_as(user_id):
    def identity():
        with session_factory()() as db:
            return db.get(User, user_id)

    app.dependency_overrides[current_user] = identity


@pytest.fixture
def showcase(client, monkeypatch):
    shared = client.post("/api/tasks", json=task_body("Shared test scenario")).json()
    url = f"/api/tasks/{shared['id']}"
    bid = client.post(url + "/quote").json()["bids"][0]
    assert client.post(url + "/select", json={"bid_id": bid["id"]}).status_code == 200
    assert client.post(url + "/pay").status_code == 200
    original = client.post(url + "/deliver").json()
    private = client.post("/api/tasks", json=task_body("Private owner task")).json()
    with session_factory()() as db:
        db.add_all(
            [
                User(id="showcase-user", name="Marketplace Demo"),
                User(id="unrelated-user", name="Unrelated user"),
            ]
        )
        db.commit()
    monkeypatch.setenv("SHOWCASE_USER_SUB", "showcase-user")
    monkeypatch.setenv("SHOWCASE_TASK_IDS", shared["id"])
    monkeypatch.setenv("SHOWCASE_AGENT_IDS", bid["agent"]["id"])
    monkeypatch.setenv("PAYMENT_OWNER_SUB", "demo-user")
    get_settings.cache_clear()
    sign_in_as("showcase-user")
    return original, private, bid


def test_showcase_reads_only_curated_records_without_copying_spending(client, showcase):
    original, private, bid = showcase
    tasks = client.get("/api/tasks").json()
    assert [t["id"] for t in tasks] == [original["id"]]
    assert tasks[0]["read_only"] is True
    assert tasks[0]["delivery"] == original["delivery"]
    assert tasks[0]["bids"] == original["bids"]
    assert tasks[0]["payment"]["id"] == original["payment"]["id"]
    assert client.get(f"/api/tasks/{private['id']}").status_code == 404
    assert client.get(f"/api/tasks/{original['id']}").json()["read_only"] is True
    payments = client.get("/api/payments").json()
    assert len(payments) == 1 and payments[0]["read_only"] is True
    assert payments[0]["id"] == original["payment"]["id"]
    agents = client.get("/api/agents?mine=true").json()
    assert [a["id"] for a in agents] == [bid["agent"]["id"]]
    assert agents[0]["read_only"] is True
    assert len(client.get("/api/agents").json()) == 8
    overview = client.get("/api/overview").json()
    assert overview["tasks"] == overview["completed"] == 1
    assert overview["spent"] == client.get("/api/me").json()["spent"] == "0.000000"
    assert all(event["task_id"] != private["id"] for event in overview["events"])
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Payment)) == 1
        assert db.get(User, "showcase-user").payment_instrument_id is None


def test_shared_task_mutations_and_wallet_binding_are_rejected(
    client, showcase, monkeypatch
):
    original, _, bid = showcase
    url = f"/api/tasks/{original['id']}"
    for action, body in [
        ("quote", {}),
        ("auto-select", {}),
        ("select", {"bid_id": bid["id"]}),
        ("pay", {}),
        ("deliver", {}),
        ("rate", {"score": 5}),
    ]:
        response = client.post(url + "/" + action, json=body)
        assert response.status_code == 403
        assert response.json()["detail"] == "Shared demo tasks are read-only."
    sign_in_as("demo-user")
    assert client.get(url).json()["read_only"] is False
    assert client.post(url + "/rate", json={"score": 5}).status_code == 200
    sign_in_as("showcase-user")
    monkeypatch.setenv("APP_MODE", "aws")
    get_settings.cache_clear()
    assert client.post("/api/me/wallet", json={}).status_code == 403
    assert client.get("/api/me/wallet").status_code == 403


def test_other_accounts_stay_isolated_and_demo_can_create_own_tasks(client, showcase):
    original, _, _ = showcase
    sign_in_as("unrelated-user")
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/payments").json() == []
    assert client.get("/api/agents?mine=true").json() == []
    assert client.get(f"/api/tasks/{original['id']}").status_code == 404
    assert (
        client.post(f"/api/tasks/{original['id']}/rate", json={"score": 1}).status_code
        == 404
    )
    sign_in_as("showcase-user")
    own = client.post("/api/tasks", json=task_body("My own demo task"))
    assert own.status_code == 201
    task_id = own.json()["id"]
    assert client.get(f"/api/tasks/{task_id}").json()["read_only"] is False
    assert client.post(f"/api/tasks/{task_id}/quote").status_code == 200
    assert client.get("/api/overview").json()["tasks"] == 2
