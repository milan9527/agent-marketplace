from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.auth import current_user
from app.db import session_factory
from app.main import app
from app.models import Agent, Task, User
from app.payments import PaymentUncertain


def create(client, **overrides):
    data = {
        "title": "Analyze the cloud developer tools market",
        "spec": "Compare the market opportunity, key risks, and developer adoption of cloud tools.",
        "category": "Research",
        "budget": "0.05",
        "deadline": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
    }
    data.update(overrides)
    response = client.post("/api/tasks", json=data)
    assert response.status_code == 201, response.text
    return response.json()


def ready_to_pay(client, **overrides):
    task = create(client, **overrides)
    response = client.post(f"/api/tasks/{task['id']}/quote")
    assert response.status_code == 200, response.text
    task = response.json()
    bid = next(b for b in task["bids"] if b["within_budget"])
    selected = client.post(
        f"/api/tasks/{task['id']}/select", json={"bid_id": bid["id"]}
    )
    assert selected.status_code == 200
    return selected.json()


def test_full_purchase_delivery_and_verified_review(client):
    agents = client.get("/api/agents").json()
    assert len(agents) == 8
    assert all(a["rating"] is None for a in agents)
    task = ready_to_pay(client)
    paid = client.post(f"/api/tasks/{task['id']}/pay").json()
    assert paid["status"] == "paid"
    assert paid["payment"]["transaction_hash"] is None
    assert paid["payment"]["provider"] == "demo"
    delivery = client.post(f"/api/tasks/{task['id']}/deliver")
    assert delivery.status_code == 200
    assert delivery.json()["status"] == "completed"
    assert task["title"] in delivery.json()["delivery"]
    assert (
        client.post(f"/api/tasks/{task['id']}/rate", json={"score": 5}).status_code
        == 200
    )
    reviewed = next(
        a for a in client.get("/api/agents").json() if a["id"] == paid["winner_id"]
    )
    assert reviewed["rating"] == 5
    assert reviewed["review_count"] == 1
    assert reviewed["completed_tasks"] == 1
    assert client.get("/api/overview").json()["completed"] == 1


def test_retries_do_not_charge_deliver_or_review_twice(client):
    task = ready_to_pay(client)
    url = f"/api/tasks/{task['id']}"
    for _ in range(3):
        assert client.post(url + "/pay").status_code == 200
    assert len(client.get("/api/payments").json()) == 1
    for _ in range(3):
        assert client.post(url + "/deliver").status_code == 200
    assert client.post(url + "/rate", json={"score": 4}).status_code == 200
    assert client.post(url + "/rate", json={"score": 1}).status_code == 409
    me = client.get("/api/me").json()
    assert Decimal(me["spent"]) == Decimal(
        client.get("/api/payments").json()[0]["amount"]
    )
    agent = next(
        a for a in client.get("/api/agents").json() if a["id"] == task["winner_id"]
    )
    assert agent["completed_tasks"] == 1 and agent["review_count"] == 1


def test_concurrent_payment_has_one_charge(client):
    task = ready_to_pay(client)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(
                lambda _: client.post(f"/api/tasks/{task['id']}/pay"), range(4)
            )
        )
    assert all(r.status_code in (200, 409) for r in responses)
    assert len(client.get("/api/payments").json()) == 1
    assert Decimal(client.get("/api/me").json()["reserved"]) == 0


def test_concurrent_tasks_cannot_exceed_account_limit(client):
    a = ready_to_pay(client, preferred_agent_id="finley")
    b = ready_to_pay(client, preferred_agent_id="finley")
    assert client.patch("/api/me/budget", json={"budget": "0.04"}).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda task: client.post(f"/api/tasks/{task['id']}/pay"), [a, b]
            )
        )
    assert sorted(r.status_code for r in responses) == [200, 422]
    assert client.get("/api/me").json()["spent"] == "0.030000"
    assert len(client.get("/api/payments").json()) == 1


def test_over_budget_bid_and_invalid_order_are_rejected(client):
    task = create(client, budget="0.01")
    url = f"/api/tasks/{task['id']}"
    assert client.post(url + "/pay").status_code == 409
    assert client.post(url + "/deliver").status_code == 409
    assert client.post(url + "/rate", json={"score": 5}).status_code == 409
    bids = client.post(url + "/quote").json()["bids"]
    assert all(not b["within_budget"] for b in bids)
    assert (
        client.post(url + "/select", json={"bid_id": bids[0]["id"]}).status_code == 422
    )


def test_task_owner_is_enforced(client):
    task = ready_to_pay(client)
    with session_factory()() as db:
        db.add(User(id="another-user", name="Another user"))
        db.commit()
    app.dependency_overrides[current_user] = lambda: User(
        id="another-user", name="Another user"
    )
    assert client.get(f"/api/tasks/{task['id']}").status_code == 404
    for action in ("pay", "quote", "deliver"):
        assert client.post(f"/api/tasks/{task['id']}/{action}").status_code == 404
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/payments").json() == []


def test_expired_task_cannot_pay(client):
    task = ready_to_pay(client)
    with session_factory()() as db:
        db.get(Task, task["id"]).deadline = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        db.commit()
    assert client.post(f"/api/tasks/{task['id']}/pay").status_code == 409
    assert client.get("/api/payments").json() == []


def test_delivery_failure_can_retry_without_recharging(client, monkeypatch):
    from app import service

    task = ready_to_pay(client)
    client.post(f"/api/tasks/{task['id']}/pay")
    original = service.call_bidders

    def fail(_):
        raise RuntimeError("Model unavailable")

    monkeypatch.setattr(service, "call_bidders", fail)
    assert client.post(f"/api/tasks/{task['id']}/deliver").status_code == 502
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "paid"
    monkeypatch.setattr(service, "call_bidders", original)
    assert client.post(f"/api/tasks/{task['id']}/deliver").status_code == 200
    assert len(client.get("/api/payments").json()) == 1


def test_uncertain_settlement_reserves_budget_and_blocks_repayment(client, monkeypatch):
    from app import service

    def uncertain(*_):
        raise PaymentUncertain("Settlement timed out; review required.")

    task = ready_to_pay(client)
    monkeypatch.setattr(service, "settle_payment", uncertain)
    assert client.post(f"/api/tasks/{task['id']}/pay").status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/pay").status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/deliver").status_code == 409
    me = client.get("/api/me").json()
    assert Decimal(me["spent"]) == 0 and Decimal(me["reserved"]) > 0
    assert client.get("/api/payments").json()[0]["status"] == "review_required"
    assert (
        client.patch("/api/me/budget", json={"budget": "0.000001"}).status_code == 422
    )


def test_input_validation_and_duplicate_wallet(client):
    payload = {
        "name": "Nova Agent",
        "tagline": "A helpful research specialist",
        "description": "Create structured research deliverables with clear assumptions.",
        "category": "Research",
        "skills": ["Research"],
        "price": "0.001",
        "wallet": "0x" + "aB" * 20,
    }
    response = client.post("/api/agents", json=payload)
    assert response.status_code == 201
    assert (
        client.post(
            "/api/agents", json={**payload, "wallet": payload["wallet"].lower()}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/agents", json={**payload, "wallet": "0x" + "0" * 40}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/agents", json={**payload, "price": "0.0000001"}).status_code
        == 422
    )
    assert (
        client.post("/api/agents", json={**payload, "price": "-1"}).status_code == 422
    )
    assert (
        client.post("/api/agents", json={**payload, "skills": [""]}).status_code == 422
    )
    assert len(client.get("/api/agents?q=Nova").json()) == 1
    assert client.get("/api/agents?q=%25").json() == []
    with session_factory()() as db:
        assert db.get(Agent, response.json()["id"]).wallet == payload["wallet"].lower()


def test_budget_validation_and_payment_failure_releases_reservation(
    client, monkeypatch
):
    from app import service

    def fail(*_):
        raise ValueError("Not configured")

    task = ready_to_pay(client)
    monkeypatch.setattr(service, "settle_payment", fail)
    assert client.post(f"/api/tasks/{task['id']}/pay").status_code == 502
    me = client.get("/api/me").json()
    assert Decimal(me["reserved"]) == 0 and Decimal(me["spent"]) == 0
    assert client.get("/api/payments").json()[0]["status"] == "failed"
