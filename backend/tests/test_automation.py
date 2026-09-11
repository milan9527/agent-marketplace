from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy import func, select

from app import service
from app.automation import advance_automation
from app.auth import current_user
from app.config import get_settings
from app.db import session_factory
from app.main import app
from app.models import Agent, AutomationJob, Event, Task, User
from app.payments import PaymentUncertain
from app.seed import seed_catalog


def create(client, **extra):
    response = client.post(
        "/api/tasks",
        json={
            "title": "Automatic market analysis",
            "spec": "Compare the supplied market data and produce a research report.",
            "category": "Research",
            "budget": "0.05",
            "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "selection_mode": "auto",
            "auto_execute": True,
            "agent_scope": "live",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def tick():
    # A fresh session mirrors separate Runtime invocations / worker restarts.
    with session_factory()() as db:
        return advance_automation(db)


def test_automatic_paid_task_completes_without_browser_payment_requests(client):
    task = create(client)
    url = "/api/tasks/" + task["id"]
    assert task["automation"]["status"] == "queued"
    assert client.post(url + "/pay").status_code == 409
    assert client.post(url + "/automate").status_code == 200
    assert tick()["stage"] == "awaiting_payment"
    assert tick()["stage"] == "paid"
    assert tick()["status"] == "completed"
    assert tick() == {"processed": False}
    result = client.get(url).json()
    assert result["status"] == "completed" and result["delivery"]
    assert result["payment"]["status"] == "settled"
    assert result["automation"]["status"] == "completed"
    assert len(client.get("/api/payments").json()) == 1
    with session_factory()() as db:
        assert db.get(Agent, result["winner_id"]).completed_tasks == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.task_id == task["id"],
                    Event.kind == "automation_authorized",
                )
            )
            == 1
        )


def test_legacy_auto_selection_does_not_authorize_payment(client):
    task = create(client, auto_execute=False)
    assert task["auto_execute"] is False
    selected = client.post(f"/api/tasks/{task['id']}/quote").json()
    assert selected["status"] == "awaiting_payment"
    assert tick() == {"processed": False}
    assert client.get("/api/payments").json() == []
    queued = client.post(f"/api/tasks/{task['id']}/automate")
    assert queued.status_code == 200 and queued.json()["auto_execute"]
    assert tick()["stage"] == "paid"
    assert tick()["status"] == "completed"


def test_automatic_demo_delivery_never_calls_payments(client, monkeypatch):
    with session_factory()() as db:
        seed_catalog(db)
    settle = MagicMock(side_effect=AssertionError("Demo must not pay"))
    monkeypatch.setattr(service, "settle_payment", settle)
    task = create(client, agent_scope="demo")
    assert tick()["stage"] == "demo_ready"
    assert tick()["status"] == "completed"
    assert client.get(f"/api/tasks/{task['id']}").json()["payment"] is None
    settle.assert_not_called()


def test_no_qualifying_bid_pauses_without_payment(client):
    task = create(client, budget="0.000001")
    assert tick()["status"] == "blocked"
    result = client.get(f"/api/tasks/{task['id']}").json()
    assert "70%" in result["automation"]["error"]
    assert result["status"] == "bidding"
    assert result["winner_id"] is None and result["payment"] is None
    assert tick() == {"processed": False}


def test_uncertain_automatic_payment_is_never_retried(client, monkeypatch):
    settle = MagicMock(side_effect=PaymentUncertain("Settlement needs reconciliation"))
    monkeypatch.setattr(service, "settle_payment", settle)
    task = create(client)
    tick()
    assert tick()["status"] == "review_required"
    for _ in range(3):
        assert tick() == {"processed": False}
    assert client.post(f"/api/tasks/{task['id']}/automate").status_code == 409
    settle.assert_called_once()
    assert client.get("/api/me").json()["spent"] == "0.000000"
    assert float(client.get("/api/me").json()["reserved"]) > 0
    assert len(client.get("/api/payments").json()) == 1


def test_delivery_retry_reuses_settled_payment(client, monkeypatch):
    task = create(client)
    tick()
    tick()
    original = service.call_bidders
    monkeypatch.setattr(
        service, "call_bidders", MagicMock(side_effect=RuntimeError("Temporary"))
    )
    result = tick()
    assert result["status"] == "queued" and result["stage"] == "paid"
    assert tick() == {"processed": False}  # Backoff is persisted.
    with session_factory()() as db:
        db.get(AutomationJob, task["id"]).available_at = 0
        db.commit()
    monkeypatch.setattr(service, "call_bidders", original)
    assert tick()["status"] == "completed"
    assert len(client.get("/api/payments").json()) == 1


def test_concurrent_workers_create_one_payment_and_delivery(client, monkeypatch):
    settle = MagicMock(wraps=service.settle_payment)
    monkeypatch.setattr(service, "settle_payment", settle)
    task = create(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: tick(), range(12)))
    for _ in range(3):
        tick()
    result = client.get(f"/api/tasks/{task['id']}").json()
    assert result["status"] == "completed"
    settle.assert_called_once()
    assert len(client.get("/api/payments").json()) == 1
    with session_factory()() as db:
        assert db.get(Agent, result["winner_id"]).completed_tasks == 1


def test_stale_lease_recovers_confirmed_stages_but_not_inflight_payment(
    client, monkeypatch
):
    first = create(client)
    tick()
    tick()
    with session_factory()() as db:
        job = db.get(AutomationJob, first["id"])
        job.status, job.lease_until, job.lease_token = "running", 0, "old-worker"
        db.commit()
    assert tick()["status"] == "completed"
    second = create(client)
    tick()
    with session_factory()() as db:
        task = db.get(Task, second["id"])
        task.status = "paying"
        job = db.get(AutomationJob, task.id)
        job.status, job.lease_until, job.lease_token = "running", 0, "old-worker"
        db.commit()
    settle = MagicMock(side_effect=AssertionError("Never retry uncertain payment"))
    monkeypatch.setattr(service, "settle_payment", settle)
    assert tick()["status"] == "review_required"
    assert client.post(f"/api/tasks/{second['id']}/automate").status_code == 409
    settle.assert_not_called()


def test_automatic_payment_obeys_delegated_spending_cap(client, monkeypatch):
    task = create(client)
    tick()
    with session_factory()() as db:
        user = db.get(User, "demo-user")
        user.payment_instrument_id = "instrument"
        user.payment_user_id = "payment-user"
        user.payment_connector_id = "connector3"
        db.commit()
    for key, value in {
        "APP_MODE": "aws",
        "PAYMENT_OWNER_SUB": "original-owner",
        "PAYMENT_DELEGATE_SUB": "demo-user",
        "PAYMENT_DELEGATE_LIMIT_MICROS": "10000",
        "PAYMENT_INSTRUMENT_ID": "instrument",
        "PAYMENT_USER_ID": "payment-user",
        "PAYMENT_CONNECTOR_ID": "connector3",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    settle = MagicMock()
    monkeypatch.setattr(service, "settle_payment", settle)
    assert tick()["status"] == "blocked"
    settle.assert_not_called()
    with session_factory()() as db:
        result = service.task_view(db.get(Task, task["id"]), db)
    assert "spending limit" in result["automation"]["error"]
    assert result["payment"] is None


def test_automation_requires_owner_and_explicit_mode(client):
    response = client.post(
        "/api/tasks",
        json={
            "title": "Invalid mode",
            "spec": "Use the supplied input data.",
            "category": "Research",
            "budget": "0.05",
            "auto_execute": True,
            "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422
    task = create(client, auto_execute=False)
    with session_factory()() as db:
        db.add(User(id="other-user", name="Other user"))
        db.commit()
    app.dependency_overrides[current_user] = lambda: User(id="other-user")
    assert client.post(f"/api/tasks/{task['id']}/automate").status_code == 404
    assert tick() == {"processed": False}


def test_concurrent_authorization_creates_one_job(client):
    task = create(client, auto_execute=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(f"/api/tasks/{task['id']}/automate"),
                range(2),
            )
        )
    assert all(r.status_code == 200 for r in responses)
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AutomationJob)) == 1
