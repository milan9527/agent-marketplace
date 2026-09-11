from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from app import service
from app.config import get_settings
from app.db import session_factory
from app.main import me
from app.models import Bid, Payment, Task, User
from app.payments import PaymentUncertain


@pytest.fixture
def delegate(client, monkeypatch):
    with session_factory()() as db:
        db.add(User(
            id="delegate", name="Marketplace Demo",
            payment_instrument_id="existing-instrument",
            payment_user_id="existing-payment-user",
            payment_connector_id="connector3",
        ))
        db.flush()
        for task_id in ("one", "two"):
            db.add(Task(
                id=task_id, owner_id="delegate", title="Delegate payment check",
                spec="Analyze supplied data.", category="Finance",
                budget_micros=10_000, status="awaiting_payment", winner_id="finley",
                deadline=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            ))
            db.flush()
            db.add(Bid(
                task_id=task_id, agent_id="finley", price_micros=10_000,
                match_score=95, quality_score=80, rationale="Relevant specialist",
            ))
        db.commit()
    for key, value in {
        "APP_MODE": "aws",
        "PAYMENT_OWNER_SUB": "demo-user",
        "PAYMENT_DELEGATE_SUB": "delegate",
        "PAYMENT_DELEGATE_LIMIT_MICROS": "10000",
        "PAYMENT_INSTRUMENT_ID": "existing-instrument",
        "PAYMENT_USER_ID": "existing-payment-user",
        "PAYMENT_CONNECTOR_ID": "connector3",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    settlement = MagicMock(return_value={
        "process_id": "process", "session_id": "session",
        "transaction_hash": "0x" + "a" * 64,
    })
    monkeypatch.setattr(service, "settle_payment", settlement)
    return settlement


def pay(task_id):
    with session_factory()() as db:
        try:
            service.process_payment(db, "delegate", task_id)
            return 200
        except HTTPException as exc:
            return exc.status_code


def test_concurrent_delegated_payments_obey_operator_cap(client, delegate):
    # The persisted personal budget is 10 USDC; the operator cap is 0.01.
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(pay, ("one", "two"))) == [200, 422]
    assert delegate.call_count == 1
    with session_factory()() as db:
        user = db.get(User, "delegate")
        assert user.spent_micros == 10_000 and user.reserved_micros == 0
        assert me(user=user)["remaining"] == "0.000000"
        assert me(user=user)["budget"] == "0.010000"
        assert me(user=user)["wallet_shared"]
        payment = db.scalar(select(Payment))
        assert payment.owner_id == user.id
        assert payment.instrument_id == "existing-instrument"
        assert payment.payer_user_id == "existing-payment-user"
        owner = db.get(User, "demo-user")
        assert owner.spent_micros == owner.reserved_micros == 0
        with pytest.raises(HTTPException) as exc:
            service.update_budget(db, user.id, {"budget": "1.00"})
        assert exc.value.status_code == 422


def test_uncertain_delegate_payment_keeps_cap_reserved(client, delegate):
    delegate.side_effect = PaymentUncertain("Review required")
    assert pay("one") == 409
    assert pay("two") == 422
    assert delegate.call_count == 1
    with session_factory()() as db:
        user = db.get(User, "delegate")
        assert user.spent_micros == 0 and user.reserved_micros == 10_000


def test_revoked_delegate_or_wrong_connector_cannot_pay(client, delegate, monkeypatch):
    with session_factory()() as db:
        db.get(User, "delegate").payment_connector_id = "different-connector"
        db.commit()
    assert pay("one") == 422
    monkeypatch.setenv("PAYMENT_DELEGATE_SUB", "")
    get_settings.cache_clear()
    assert pay("two") == 403
    delegate.assert_not_called()


def test_delegate_cannot_pay_other_accounts_tasks(client, delegate):
    with session_factory()() as db:
        db.get(Task, "one").owner_id = "demo-user"
        db.commit()
    assert pay("one") == 404
    delegate.assert_not_called()
