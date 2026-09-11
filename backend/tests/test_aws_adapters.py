from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.validate import validate_parameters
from fastapi.testclient import TestClient

from app import payments
from app.config import get_settings
from app.runtime import app as runtime_app


def test_payment_proof_is_not_treated_as_settlement(monkeypatch):
    settings = SimpleNamespace(
        app_mode="aws",
        payment_manager_arn="arn:aws:bedrock-agentcore:us-west-2:123456789012:payment-manager/test-0123456789",
        chain_network="eip155:84532",
        usdc_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        facilitator_token="",
        facilitator_url="https://facilitator.example",
    )
    monkeypatch.setattr(payments, "get_settings", lambda: settings)
    sdk = MagicMock()
    sdk.create_payment_session.return_value = {
        "paymentSession": {
            "paymentSessionId": "payment-session-123456789012345",
            "paymentManagerArn": settings.payment_manager_arn,
            "userId": "existing-privy-user",
            "expiryTimeInMinutes": 60,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }
    }
    sdk.process_payment.return_value = {
        "status": "PROOF_GENERATED",
        "processPaymentId": "a" * 36,
        "paymentOutput": {
            "cryptoX402": {"version": "2", "payload": {"signature": "never-log-me"}}
        },
    }
    monkeypatch.setattr(payments, "payment_client", lambda: sdk)
    http = MagicMock()
    http.__enter__.return_value = http
    http.post.return_value.json.return_value = {"isValid": True, "success": False}
    monkeypatch.setattr(payments.httpx, "Client", lambda **_: http)
    payment = SimpleNamespace(
        id="12345678-1234-1234-1234-123456789012",
        amount_micros=30000,
        session_id=None,
        process_id=None,
        payer_user_id="existing-privy-user",
        instrument_id="payment-instrument-123456789012345",
    )
    user = SimpleNamespace(
        id="user", payment_instrument_id="payment-instrument-123456789012345"
    )
    task = SimpleNamespace(id="task", budget_micros=50000)
    agent = SimpleNamespace(wallet="0x" + "1" * 40)
    with pytest.raises(payments.PaymentUncertain):
        payments.settle_payment(payment, user, agent, task, lambda: None)
    assert (
        sdk.process_payment.call_args.kwargs["paymentInput"]["cryptoX402"]["payload"][
            "amount"
        ]
        == "30000"
    )
    assert sdk.process_payment.call_args.kwargs["userId"] == "existing-privy-user"
    assert (
        sdk.create_payment_session.call_args.kwargs["userId"] == "existing-privy-user"
    )
    assert payment.session_id == "payment-session-123456789012345"
    assert (
        sdk.process_payment.call_args.kwargs["paymentSessionId"] == payment.session_id
    )
    assert http.post.call_args_list[0].args[0].endswith("/verify")
    assert http.post.call_args_list[1].args[0].endswith("/settle")
    verification_body = http.post.call_args_list[0].kwargs["json"]
    assert verification_body["paymentPayload"]["x402Version"] == 2
    assert (
        verification_body["paymentPayload"]["accepted"]
        == verification_body["paymentRequirements"]
    )
    assert (
        verification_body["paymentPayload"]["payload"]
        == sdk.process_payment.return_value["paymentOutput"]["cryptoX402"]["payload"]
    )
    assert http.post.call_args_list[1].kwargs["json"] == verification_body
    # Validate against the installed AWS SDK service model, not a guessed API.
    model = boto3.client(
        "bedrock-agentcore",
        region_name="us-west-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    ).meta.service_model
    validate_parameters(
        sdk.process_payment.call_args.kwargs,
        model.operation_model("ProcessPayment").input_shape,
    )
    validate_parameters(
        sdk.create_payment_session.call_args.kwargs,
        model.operation_model("CreatePaymentSession").input_shape,
    )
    validate_parameters(
        sdk.create_payment_session.return_value,
        model.operation_model("CreatePaymentSession").output_shape,
    )


def test_success_requires_receipt_and_matching_network(monkeypatch):
    settings = SimpleNamespace(
        app_mode="aws",
        payment_manager_arn="test",
        chain_network="eip155:84532",
        usdc_address="0x" + "2" * 40,
        facilitator_token="",
        facilitator_url="https://facilitator.example",
    )
    monkeypatch.setattr(payments, "get_settings", lambda: settings)
    sdk = MagicMock()
    sdk.process_payment.return_value = {
        "status": "PROOF_GENERATED",
        "processPaymentId": "id",
        "paymentOutput": {"cryptoX402": {"payload": {"proof": "sensitive"}}},
    }
    monkeypatch.setattr(payments, "payment_client", lambda: sdk)
    http = MagicMock()
    http.__enter__.return_value = http
    http.post.return_value.json.return_value = {
        "isValid": True,
        "success": True,
        "network": "eip155:84532",
        "transaction": "0x" + "a" * 64,
    }
    monkeypatch.setattr(payments.httpx, "Client", lambda **_: http)
    result = payments.settle_payment(
        SimpleNamespace(
            id="p",
            session_id="s",
            amount_micros=1,
            payer_user_id="existing-user",
            instrument_id="existing-instrument",
        ),
        SimpleNamespace(id="u", payment_instrument_id="i"),
        SimpleNamespace(wallet="0x" + "1" * 40),
        SimpleNamespace(id="t", budget_micros=1),
        lambda: None,
    )
    assert result["transaction_hash"] == "0x" + "a" * 64
    assert "proof" not in result


def test_runtime_http_contract(monkeypatch):
    monkeypatch.setenv("RUNTIME_ROLE", "bidders")
    monkeypatch.setenv("APP_MODE", "demo")
    get_settings.cache_clear()
    with TestClient(runtime_app) as client:
        assert client.get("/ping").json() == {"status": "Healthy"}
        response = client.post(
            "/invocations",
            json={
                "action": "quote",
                "task": {"category": "Research"},
                "agents": [{"id": "a", "category": "Research", "skills": ["research"]}],
            },
        )
        assert response.status_code == 200
        assert response.json()["bids"][0]["match_score"] == 94
    get_settings.cache_clear()
