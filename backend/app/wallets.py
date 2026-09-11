"""Read and bind an existing AgentCore Stripe/Privy wallet. Never create one."""

from decimal import Decimal
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from fastapi import HTTPException

from app.config import get_settings
from app.payments import payment_client


def inspect_existing_wallet(settings=None, client=None, control=None) -> dict:
    settings = settings or get_settings()
    for name in ("payment_manager_arn", "payment_instrument_id", "payment_user_id"):
        if not getattr(settings, name):
            raise HTTPException(
                503, "The existing Stripe/Privy payment wallet has not been configured."
            )
    client = client or payment_client()
    params = {
        "paymentManagerArn": settings.payment_manager_arn,
        "paymentInstrumentId": settings.payment_instrument_id,
        "userId": settings.payment_user_id,
    }
    if settings.payment_connector_id:
        params["paymentConnectorId"] = settings.payment_connector_id
    instrument = client.get_payment_instrument(**params)["paymentInstrument"]
    if (
        instrument["paymentInstrumentId"] != settings.payment_instrument_id
        or instrument["paymentManagerArn"] != settings.payment_manager_arn
        or instrument["userId"] != settings.payment_user_id
    ):
        raise HTTPException(
            409, "The existing wallet does not match the configured payment identity."
        )
    connector_id = instrument["paymentConnectorId"]
    if settings.payment_connector_id and connector_id != settings.payment_connector_id:
        raise HTTPException(409, "The wallet belongs to a different payment connector.")
    control = control or boto3.client(
        "bedrock-agentcore-control",
        region_name=settings.aws_region,
        config=Config(read_timeout=30, retries={"max_attempts": 1}),
    )
    connector = control.get_payment_connector(
        paymentManagerId=settings.payment_manager_arn.rsplit("/", 1)[-1],
        paymentConnectorId=connector_id,
    )
    if connector["type"] != "StripePrivy":
        raise HTTPException(
            409, "This marketplace requires an existing Stripe/Privy wallet."
        )
    if connector["status"] != "READY":
        raise HTTPException(409, "The Stripe/Privy connector is not ready.")
    wallet = instrument["paymentInstrumentDetails"].get("embeddedCryptoWallet", {})
    if wallet.get("network") != "ETHEREUM":
        raise HTTPException(
            409, "Base Sepolia payments require an Ethereum-compatible Privy wallet."
        )
    if instrument["status"] != "ACTIVE":
        raise HTTPException(
            409,
            f"The existing wallet is {instrument['status'].lower()}. Activate it in Privy first.",
        )
    balance_result = client.get_payment_instrument_balance(
        **{
            **params,
            "paymentConnectorId": connector_id,
            "chain": "BASE_SEPOLIA",
            "token": "USDC",
        }
    )
    balance = balance_result["tokenBalance"]
    if (
        balance["chain"] != "BASE_SEPOLIA"
        or balance["token"] != "USDC"
        or balance["decimals"] != 6
    ):
        raise HTTPException(
            502, "The wallet provider returned an unexpected token balance."
        )
    wallet_url = settings.privy_wallet_url or wallet.get("redirectUrl")
    if wallet_url and urlparse(wallet_url).scheme != "https":
        wallet_url = None
    return {
        "provider": "Stripe / Privy",
        "status": instrument["status"],
        "instrument_id": instrument["paymentInstrumentId"],
        "payment_user_id": instrument["userId"],
        "connector_id": connector_id,
        "address": wallet.get("walletAddress"),
        "balance": format(
            Decimal(balance["amount"]) / 10 ** balance["decimals"], ".6f"
        ),
        "network": "Base Sepolia",
        "wallet_url": wallet_url,
    }


def delegated_payment_limit(user_id: str) -> int | None:
    """A separate, operator-controlled allowance; showcase access grants none."""
    settings = get_settings()
    if (
        settings.app_mode == "aws"
        and settings.payment_owner_sub
        and user_id != settings.payment_owner_sub
        and user_id == settings.payment_delegate_sub
    ):
        return settings.payment_delegate_limit_micros
    return None


def authorize_wallet_owner(user):
    settings = get_settings()
    if not settings.payment_owner_sub:
        raise HTTPException(
            503, "Assign this wallet to your account before connecting it."
        )
    if (
        user.id != settings.payment_owner_sub
        and delegated_payment_limit(user.id) is None
    ):
        raise HTTPException(
            403, "This payment wallet is assigned to another workspace account."
        )
    return settings


def validate_wallet_binding(user, settings):
    if (
        not user.payment_instrument_id
        or user.payment_instrument_id != settings.payment_instrument_id
        or user.payment_user_id != settings.payment_user_id
        or (
            settings.payment_connector_id
            and user.payment_connector_id != settings.payment_connector_id
        )
    ):
        raise HTTPException(422, "Connect the configured Stripe/Privy wallet first")


def bind_existing_wallet(db, user):
    settings = authorize_wallet_owner(user)
    if (
        user.payment_instrument_id
        and (
            user.payment_instrument_id != settings.payment_instrument_id
            or user.payment_user_id != settings.payment_user_id
            or (
                settings.payment_connector_id
                and user.payment_connector_id != settings.payment_connector_id
            )
        )
    ):
        raise HTTPException(
            409, "A different wallet is already bound. Contact your workspace operator."
        )
    info = inspect_existing_wallet(settings)
    user.payment_instrument_id = info["instrument_id"]
    user.payment_user_id = info["payment_user_id"]
    user.payment_connector_id = info["connector_id"]
    user.wallet_address = info["address"]
    user.wallet_url = info["wallet_url"]
    from app.service import record

    record(
        db,
        user.id,
        "wallet_connected",
        "Connected the existing Stripe/Privy payment wallet",
    )
    db.commit()
    return {**info, "message": "Your existing Stripe/Privy wallet is connected."}
