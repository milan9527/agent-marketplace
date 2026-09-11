"""AgentCore generates a proof; only facilitator settlement means money was paid."""

import hashlib
import re

import boto3
import httpx
from botocore.config import Config

from app.config import get_settings
from app.schemas import money


class PaymentUncertain(Exception):
    """Proof may be signed/spent. Preserve reservation and require reconciliation."""


def payment_client():
    return boto3.client(
        "bedrock-agentcore",
        region_name=get_settings().aws_region,
        config=Config(read_timeout=60, retries={"max_attempts": 0}),
    )


def requirements(amount: int, recipient: str) -> dict:
    settings = get_settings()
    return {
        "scheme": "exact",
        "network": settings.chain_network,
        "amount": str(amount),
        "asset": settings.usdc_address,
        "payTo": recipient,
        "maxTimeoutSeconds": 300,
        "extra": {"name": "USDC", "version": "2"},
    }


def settle_payment(payment, user, agent, task, save_session) -> dict:
    settings = get_settings()
    if settings.app_mode == "demo":
        return {
            "process_id": f"demo-{payment.id}",
            "session_id": f"demo-{task.id}",
            "transaction_hash": None,
        }
    if (
        not settings.payment_manager_arn
        or not payment.instrument_id
        or not payment.payer_user_id
    ):
        raise ValueError(
            "Connect the existing Stripe/Privy payment wallet before paying."
        )
    client = payment_client()
    if not payment.session_id:
        session = client.create_payment_session(
            userId=payment.payer_user_id,
            paymentManagerArn=settings.payment_manager_arn,
            expiryTimeInMinutes=60,
            limits={
                "maxSpendAmount": {
                    "value": money(task.budget_micros),
                    "currency": "USD",
                }
            },
            clientToken=hashlib.sha256(f"session-{payment.id}".encode()).hexdigest(),
        )
        payment.session_id = session["paymentSession"]["paymentSessionId"]
        save_session()
    challenge = requirements(payment.amount_micros, agent.wallet)
    # A timeout after ProcessPayment starts can occur after signing: never retry a
    # new authorization or release the reservation without reconciliation.
    try:
        result = client.process_payment(
            userId=payment.payer_user_id,
            agentName="marketplace-orchestrator",
            paymentManagerArn=settings.payment_manager_arn,
            paymentSessionId=payment.session_id,
            paymentInstrumentId=payment.instrument_id,
            paymentType="CRYPTO_X402",
            paymentInput={"cryptoX402": {"version": "2", "payload": challenge}},
            clientToken=payment.id,
        )
        if result.get("status") != "PROOF_GENERATED":
            raise PaymentUncertain("Payment proof was not confirmed.")
        payment.process_id = result["processPaymentId"]
        save_session()
        proof = result["paymentOutput"]["cryptoX402"]["payload"]
        headers = (
            {"Authorization": f"Bearer {settings.facilitator_token}"}
            if settings.facilitator_token
            else {}
        )
        body = {
            "x402Version": 2,
            "paymentPayload": {
                "x402Version": 2,
                "accepted": challenge,
                "payload": proof,
            },
            "paymentRequirements": challenge,
        }
        with httpx.Client(timeout=60, follow_redirects=False) as http:
            verified = http.post(
                settings.facilitator_url.rstrip("/") + "/verify",
                json=body,
                headers=headers,
            )
            verified.raise_for_status()
            if verified.json().get("isValid") is not True:
                raise PaymentUncertain(
                    "The facilitator did not verify the signed proof."
                )
            settled = http.post(
                settings.facilitator_url.rstrip("/") + "/settle",
                json=body,
                headers=headers,
            )
            settled.raise_for_status()
            receipt = settled.json()
        if (
            receipt.get("success") is not True
            or receipt.get("network") != settings.chain_network
            or not re.fullmatch(r"0x[0-9a-fA-F]{64}", receipt.get("transaction", ""))
        ):
            raise PaymentUncertain(
                "The facilitator did not return a valid settlement receipt."
            )
        return {
            "process_id": payment.process_id,
            "session_id": payment.session_id,
            "transaction_hash": receipt["transaction"],
        }
    except PaymentUncertain:
        raise
    except Exception:
        raise PaymentUncertain(
            "Settlement is not confirmed. The budget remains reserved; an operator must reconcile this payment."
        ) from None
