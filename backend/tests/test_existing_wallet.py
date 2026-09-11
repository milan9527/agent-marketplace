from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
from botocore.validate import validate_parameters
from fastapi import HTTPException
import pytest

from app import wallets
from app.db import session_factory
from app.models import User


@pytest.fixture
def existing_wallet(monkeypatch):
    settings = SimpleNamespace(
        payment_manager_arn="arn:aws:bedrock-agentcore:us-west-2:123456789012:payment-manager/existing-0123456789",
        payment_instrument_id="payment-instrument-123456789012345",
        payment_user_id="privy-existing-user",
        payment_connector_id="privy-0123456789",
        payment_owner_sub="demo-user",
        privy_wallet_url="https://wallet.example.com",
        aws_region="us-west-2",
    )
    dp, cp = MagicMock(), MagicMock()
    dp.get_payment_instrument.return_value = {
        "paymentInstrument": {
            "paymentInstrumentId": settings.payment_instrument_id,
            "paymentManagerArn": settings.payment_manager_arn,
            "paymentConnectorId": settings.payment_connector_id,
            "userId": settings.payment_user_id,
            "status": "ACTIVE",
            "paymentInstrumentDetails": {
                "embeddedCryptoWallet": {
                    "network": "ETHEREUM",
                    "walletAddress": "0x" + "a" * 40,
                },
            },
        }
    }
    dp.get_payment_instrument_balance.return_value = {
        "tokenBalance": {
            "chain": "BASE_SEPOLIA",
            "token": "USDC",
            "amount": "1250000",
            "decimals": 6,
        }
    }
    cp.get_payment_connector.return_value = {"type": "StripePrivy", "status": "READY"}
    monkeypatch.setattr(wallets, "get_settings", lambda: settings)
    monkeypatch.setattr(wallets, "payment_client", lambda: dp)
    original_boto_client = boto3.client
    monkeypatch.setattr(
        wallets.boto3,
        "client",
        lambda *args, **kwargs: (
            cp
            if args[0] == "bedrock-agentcore-control"
            else original_boto_client(*args, **kwargs)
        ),
    )
    return settings, dp, cp


def test_bind_reuses_instrument_without_creating_wallet(client, existing_wallet):
    settings, dp, cp = existing_wallet
    with session_factory()() as db:
        user = db.get(User, "demo-user")
        result = wallets.bind_existing_wallet(db, user)
        assert user.payment_instrument_id == settings.payment_instrument_id
        assert user.payment_user_id == "privy-existing-user"
        assert user.id != user.payment_user_id
        assert result["balance"] == "1.250000"
        assert result["provider"] == "Stripe / Privy"
    dp.create_payment_instrument.assert_not_called()
    dp.process_payment.assert_not_called()
    cp.create_payment_connector.assert_not_called()
    model = boto3.client(
        "bedrock-agentcore",
        region_name="us-west-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    ).meta.service_model
    validate_parameters(
        dp.get_payment_instrument.call_args.kwargs,
        model.operation_model("GetPaymentInstrument").input_shape,
    )
    validate_parameters(
        dp.get_payment_instrument_balance.call_args.kwargs,
        model.operation_model("GetPaymentInstrumentBalance").input_shape,
    )


def test_wallet_is_only_available_to_designated_account(existing_wallet):
    _, dp, _ = existing_wallet
    with pytest.raises(HTTPException) as exc:
        wallets.authorize_wallet_owner(SimpleNamespace(id="another-user"))
    assert exc.value.status_code == 403
    dp.get_payment_instrument.assert_not_called()


def test_wrong_provider_or_user_cannot_be_bound(existing_wallet):
    settings, dp, cp = existing_wallet
    cp.get_payment_connector.return_value = {"type": "CoinbaseCDP", "status": "READY"}
    with pytest.raises(HTTPException, match="Stripe/Privy"):
        wallets.inspect_existing_wallet(settings)
    cp.get_payment_connector.return_value = {"type": "StripePrivy", "status": "READY"}
    dp.get_payment_instrument.return_value["paymentInstrument"]["userId"] = (
        "someone-else"
    )
    with pytest.raises(HTTPException, match="payment identity"):
        wallets.inspect_existing_wallet(settings)


def test_inactive_wallet_is_rejected(existing_wallet):
    settings, dp, _ = existing_wallet
    dp.get_payment_instrument.return_value["paymentInstrument"]["status"] = "BLOCKED"
    with pytest.raises(HTTPException, match="blocked"):
        wallets.inspect_existing_wallet(settings)
