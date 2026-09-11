"""Read-only validation of an existing AgentCore Stripe/Privy payment wallet."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings  # noqa: E402
from app.wallets import inspect_existing_wallet  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--manager-arn")
parser.add_argument("--instrument-id")
parser.add_argument("--user-id")
parser.add_argument("--connector-id")
parser.add_argument("--region")
args = parser.parse_args()
overrides = {
    key: value
    for key, value in {
        "payment_manager_arn": args.manager_arn,
        "payment_instrument_id": args.instrument_id,
        "payment_user_id": args.user_id,
        "payment_connector_id": args.connector_id,
        "aws_region": args.region,
    }.items()
    if value is not None
}
settings = Settings(**overrides)
# Explicit clients use the selected region rather than process-global settings.
import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402
from fastapi import HTTPException  # noqa: E402

try:
    config = Config(read_timeout=30, retries={"max_attempts": 1})
    info = inspect_existing_wallet(
        settings,
        client=boto3.client(
            "bedrock-agentcore", region_name=settings.aws_region, config=config
        ),
        control=boto3.client(
            "bedrock-agentcore-control", region_name=settings.aws_region, config=config
        ),
    )
    # Output is limited to identifiers, address, status, and balance.
    print(json.dumps(info, indent=2))
except HTTPException as exc:
    raise SystemExit(exc.detail) from None
except Exception as exc:
    raise SystemExit(
        f"Could not inspect the existing wallet ({type(exc).__name__}). Check AWS identity, region, and permissions."
    ) from None
