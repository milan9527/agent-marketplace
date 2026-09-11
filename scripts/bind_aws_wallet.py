"""Bind the stack's existing payment instrument to its configured Cognito owner."""

import argparse
import json
from pathlib import Path
import time

import boto3

REMOTE_CODE = """
import json, os
from datetime import datetime, timezone
from sqlalchemy import func, select
from app.config import get_settings
from app.db import session_factory
from app.main import me, wallet_status
from app.models import Payment, User
from app.wallets import bind_existing_wallet

settings = get_settings()
assert settings.app_mode == "aws"
for key in ("payment_owner_sub", "payment_instrument_id", "payment_user_id", "payment_connector_id"):
    assert getattr(settings, key) == os.environ["BIND_EXPECTED_" + key.upper()]
owner = settings.payment_owner_sub
with session_factory()() as db:
    user = db.get(User, owner)
    if user is None:
        raise RuntimeError("The configured owner must sign in once before binding.")
    baseline = (user.budget_micros, user.spent_micros, user.reserved_micros)
    payment_count = db.scalar(select(func.count()).select_from(Payment).where(Payment.owner_id == owner))
    if user.payment_instrument_id:
        if (user.payment_instrument_id != settings.payment_instrument_id
            or user.payment_user_id != settings.payment_user_id
            or user.payment_connector_id != settings.payment_connector_id):
            raise RuntimeError("A different wallet is already bound; refusing to replace it.")
        changed = False
    else:
        bind_existing_wallet(db, user)
        changed = True
with session_factory()() as db:
    user = db.get(User, owner)
    account = me(user=user)
    wallet = wallet_status(user=user)
    assert account["wallet_connected"]
    assert account["wallet_address"] == wallet["address"]
    assert wallet["status"] == "ACTIVE"
    assert user.payment_instrument_id == settings.payment_instrument_id
    assert user.payment_user_id == settings.payment_user_id
    assert user.payment_connector_id == settings.payment_connector_id
    assert (user.budget_micros, user.spent_micros, user.reserved_micros) == baseline
    assert db.scalar(select(func.count()).select_from(Payment).where(Payment.owner_id == owner)) == payment_count
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "owner_sub": owner,
        "wallet_connected": account["wallet_connected"],
        "binding_created": changed,
        "wallet": wallet,
        "payments_created": 0,
        "spending_unchanged": True,
        "binding_persisted": True,
        "wallet_api_handler_verified": True,
        "payment_tested": False,
    }
print("WALLET_BINDING_RESULT " + json.dumps(report), flush=True)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="AgentMarketplace")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", default="artifacts/aws-wallet-binding.json")
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)[
        "Stacks"
    ][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise SystemExit("Wait for the stack deployment to complete before binding.")
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    parameters = {
        item["ParameterKey"]: item.get("ParameterValue", "")
        for item in stack["Parameters"]
    }
    mapping = {
        "payment_owner_sub": "PaymentOwnerSub",
        "payment_instrument_id": "PaymentInstrumentId",
        "payment_user_id": "PaymentUserId",
        "payment_connector_id": "PaymentConnectorId",
    }
    if any(not parameters.get(name) for name in mapping.values()):
        raise SystemExit(
            "Configure the existing instrument, user, connector, and owner first."
        )
    user = session.client("cognito-idp").admin_get_user(
        UserPoolId=outputs["UserPoolId"], Username=parameters["PaymentOwnerSub"]
    )
    attributes = {item["Name"]: item["Value"] for item in user["UserAttributes"]}
    if (
        not user["Enabled"]
        or user["UserStatus"] != "CONFIRMED"
        or attributes["sub"] != parameters["PaymentOwnerSub"]
    ):
        raise SystemExit(
            "The configured owner must be an enabled, confirmed Cognito user."
        )
    ecs = session.client("ecs")
    definition = ecs.describe_task_definition(
        taskDefinition=outputs["MigrationTaskDefinition"]
    )["taskDefinition"]
    container = next(
        c for c in definition["containerDefinitions"] if c["name"] == "api"
    )
    logging = container["logConfiguration"]["options"]
    response = ecs.run_task(
        cluster=outputs["MigrationCluster"],
        taskDefinition=outputs["MigrationTaskDefinition"],
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": [outputs["MigrationSubnet"]],
                "securityGroups": [outputs["MigrationSecurityGroup"]],
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": "api",
                    "command": ["python", "-c", REMOTE_CODE],
                    "environment": [
                        {
                            "name": "BIND_EXPECTED_" + key.upper(),
                            "value": parameters[value],
                        }
                        for key, value in mapping.items()
                    ],
                }
            ]
        },
    )
    if response.get("failures") or not response.get("tasks"):
        raise SystemExit("Could not start the wallet binding task.")
    arn = response["tasks"][0]["taskArn"]
    print("Wallet binding task:", arn, flush=True)
    for _ in range(120):
        task = ecs.describe_tasks(cluster=outputs["MigrationCluster"], tasks=[arn])[
            "tasks"
        ][0]
        if task["lastStatus"] == "STOPPED":
            result = next(c for c in task["containers"] if c["name"] == "api")
            if result.get("exitCode") != 0:
                raise SystemExit(
                    "Wallet binding failed. Inspect this task's CloudWatch logs."
                )
            break
        time.sleep(5)
    else:
        raise SystemExit("Binding is still running. Inspect the task before retrying.")
    logs = session.client("logs")
    stream = f"{logging['awslogs-stream-prefix']}/api/{arn.rsplit('/', 1)[-1]}"
    for _ in range(6):
        events = logs.get_log_events(
            logGroupName=logging["awslogs-group"],
            logStreamName=stream,
            startFromHead=True,
        )["events"]
        for event in events:
            if event["message"].startswith("WALLET_BINDING_RESULT "):
                report = json.loads(event["message"].split(" ", 1)[1])
                report["owner_email"] = attributes.get("email")
                report["task_arn"] = arn
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps(report, indent=2))
                print(f"Wallet binding verified. Report: {path}")
                return
        time.sleep(2)
    raise SystemExit(
        "Task succeeded but its report is not yet available in CloudWatch."
    )


if __name__ == "__main__":
    main()
