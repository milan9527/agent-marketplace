from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from app.auth import current_user
from app.db import session_factory
from app.main import app
from app.models import Agent, Bid, Payment, Task, User
from app.seed import seed_catalog


def task_input(**extra):
    return {
        "title": "Research a new developer product",
        "spec": "Compare developer needs and practical product positioning.",
        "category": "Research",
        "budget": "0.05",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        **extra,
    }


def test_shared_catalog_is_idempotent_and_visible_to_new_users(client):
    with session_factory()() as db:
        original = db.get(Agent, "atlas").description
        assert seed_catalog(db)["added"] == 8
        db.get(Agent, "demo-atlas").tagline = "Preserve existing catalog edits."
        db.add(User(id="new-builder", name="New builder"))
        db.commit()
        assert seed_catalog(db)["added"] == 0
        assert db.get(Agent, "demo-atlas").tagline == "Preserve existing catalog edits."
        assert db.get(Agent, "atlas").description == original
        assert db.scalar(select(func.count()).select_from(Agent)) == 16
    app.dependency_overrides[current_user] = lambda: User(
        id="new-builder", name="New builder"
    )
    previews = [a for a in client.get("/api/agents").json() if a["is_demo"]]
    assert len(previews) == 8
    assert all(a["bookable"] is True and a["wallet"] is None for a in previews)
    assert all(a["rating"] is None and a["completed_tasks"] == 0 for a in previews)
    assert client.get("/api/agents?mine=true").json() == []
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/payments").json() == []


def test_demo_catalog_supports_complete_workflow_without_payment(client, monkeypatch):
    def must_not_pay(*args, **kwargs):
        raise AssertionError("A demo run must not access any payment provider")

    monkeypatch.setattr("app.service.settle_payment", must_not_pay)
    with session_factory()() as db:
        seed_catalog(db)
        db.execute(
            update(Agent).where(Agent.owner_id == "demo-user").values(active=False)
        )
        db.commit()
    # Match the live environment: only the shared demo catalog is available.
    task = client.post("/api/tasks", json=task_input()).json()
    response = client.post(f"/api/tasks/{task['id']}/quote")
    assert response.status_code == 200
    assert len(response.json()["bids"]) == 8
    assert response.json()["is_demo"] is True
    bid = response.json()["bids"][0]
    url = f"/api/tasks/{task['id']}"
    selected = client.post(url + "/select", json={"bid_id": bid["id"]})
    assert selected.json()["status"] == "demo_ready"
    assert selected.json()["payment"] is None
    assert client.post(url + "/pay").status_code == 409
    delivered = client.post(url + "/deliver")
    assert delivered.status_code == 200
    assert delivered.json()["status"] == "completed"
    assert delivered.json()["is_demo"] is True
    assert "Demo deliverable · No payment was made." in delivered.json()["delivery"]
    assert (
        client.post(url + "/deliver").json()["delivery"] == delivered.json()["delivery"]
    )
    assert client.post(url + "/rate", json={"score": 5}).status_code == 200
    assert client.post(url + "/rate", json={"score": 4}).status_code == 409
    assert client.get("/api/payments").json() == []
    assert client.get("/api/me").json()["spent"] == "0.000000"
    assert client.get("/api/me").json()["reserved"] == "0.000000"
    with session_factory()() as db:
        agent = db.get(Agent, bid["agent"]["id"])
        assert agent.reputation_count == 0 and agent.completed_tasks == 0


def test_direct_demo_task_retry_and_owner_isolation(client, monkeypatch):
    with session_factory()() as db:
        seed_catalog(db)
    response = client.post(
        "/api/tasks", json=task_input(preferred_agent_id="demo-atlas")
    )
    assert response.status_code == 201 and response.json()["is_demo"]
    url = f"/api/tasks/{response.json()['id']}"
    assert client.post(url + "/deliver").status_code == 409
    bid = client.post(url + "/quote").json()["bids"][0]
    assert client.post(url + "/select", json={"bid_id": bid["id"]}).status_code == 200
    attempts = []

    def delivery(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise RuntimeError("Model temporarily unavailable")
        return {"delivery": "# Demo result"}

    monkeypatch.setattr("app.service.call_bidders", delivery)
    assert client.post(url + "/deliver").status_code == 502
    assert client.get(url).json()["status"] == "demo_ready"
    assert client.post(url + "/deliver").status_code == 200
    assert len(attempts) == 2
    with session_factory()() as db:
        db.add(User(id="another-builder", name="Another builder"))
        db.commit()
    app.dependency_overrides[current_user] = lambda: User(
        id="another-builder", name="Another builder"
    )
    assert client.get(url).status_code == 404
    for action in ("quote", "pay", "deliver"):
        assert client.post(url + "/" + action).status_code == 404
    assert client.post(url + "/rate", json={"score": 5}).status_code == 404


def test_demo_flags_cannot_bypass_live_agent_payment(client, monkeypatch):
    assert client.post("/api/tasks", json=task_input(is_demo=True)).status_code == 422
    task = client.post("/api/tasks", json=task_input(preferred_agent_id="atlas")).json()
    url = f"/api/tasks/{task['id']}"
    bid = client.post(url + "/quote").json()["bids"][0]
    selected = client.post(url + "/select", json={"bid_id": bid["id"]}).json()
    assert selected["status"] == "awaiting_payment" and selected["is_demo"] is False

    def must_not_generate(*args, **kwargs):
        raise AssertionError("Live agents require confirmed payment")

    monkeypatch.setattr("app.service.call_bidders", must_not_generate)
    assert client.post(url + "/deliver").status_code == 409
    with session_factory()() as db:
        db.get(Task, task["id"]).status = "demo_ready"
        db.commit()
    assert client.post(url + "/deliver").status_code == 409


def test_demo_payment_is_rejected_before_reserving_or_calling_provider(
    client, monkeypatch
):
    def must_not_pay(*args, **kwargs):
        raise AssertionError("Demo catalog must never call a payment provider")

    monkeypatch.setattr("app.service.settle_payment", must_not_pay)
    with session_factory()() as db:
        seed_catalog(db)
        task = Task(
            owner_id="demo-user",
            title="Legacy preview task",
            spec="Example task",
            category="Research",
            budget_micros=50000,
            deadline=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            status="awaiting_payment",
            winner_id="demo-atlas",
        )
        db.add(task)
        db.flush()
        db.add(
            Bid(
                task_id=task.id,
                agent_id="demo-atlas",
                price_micros=40000,
                match_score=90,
                quality_score=80,
                rationale="Example quote",
            )
        )
        db.commit()
        task_id = task.id
    response = client.post(f"/api/tasks/{task_id}/pay")
    assert response.status_code == 409
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Payment)) == 0
        assert db.get(User, "demo-user").reserved_micros == 0
        assert db.get(Task, task_id).status == "awaiting_payment"
