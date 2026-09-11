"""Publish and run the bounded Northstar scenarios through the deployed AgentCore Runtime."""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

import boto3
from botocore.config import Config
import httpx

from aws_workspace_snapshot import snapshot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402
from app.wallets import inspect_existing_wallet  # noqa: E402

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def verify_receipt(tx_hash, sender, recipient, amount):
    def rpc(method, params):
        response = httpx.post(
            "https://sepolia.base.org",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise RuntimeError(f"Read-only chain verification failed: {body['error']}")
        return body["result"]

    if int(rpc("eth_chainId", []), 16) != 84532:
        raise RuntimeError("Unexpected chain during receipt verification.")
    receipt = rpc("eth_getTransactionReceipt", [tx_hash])
    if not receipt or receipt["status"] != "0x1":
        raise RuntimeError("The payment transaction is not confirmed successful.")
    matched = [
        log
        for log in receipt["logs"]
        if log["address"].lower() == "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
        and len(log["topics"]) == 3
        and log["topics"][0].lower() == TRANSFER_TOPIC
        and log["topics"][1][-40:].lower() == sender[2:].lower()
        and log["topics"][2][-40:].lower() == recipient[2:].lower()
        and int(log["data"], 16) == amount
    ]
    if not matched:
        raise RuntimeError("Receipt lacks the expected USDC transfer.")
    return {
        "transaction_hash": tx_hash,
        "block_number": int(receipt["blockNumber"], 16),
        "chain_id": 84532,
        "usdc_transfer_verified": True,
        "payer": sender,
        "recipient": recipient,
        "amount_micros": amount,
        "explorer_url": f"https://sepolia.basescan.org/tx/{tx_hash}",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="AgentMarketplace")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--fixtures", type=Path, default=ROOT / "examples/business-scenarios.json"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts/business-scenarios"
    )
    parser.add_argument("--initial-snapshot", type=Path)
    args = parser.parse_args()
    fixtures = json.loads(args.fixtures.read_text())
    cap = Decimal(fixtures["max_total_payment"])
    # This job is explicitly limited to three small testnet payments.
    if (
        not 0 < cap <= Decimal("0.03")
        or sum(Decimal(t["budget"]) for t in fixtures["tasks"]) > cap
    ):
        raise RuntimeError("Scenario budgets exceed the 0.03 test-USDC execution cap.")
    session = boto3.Session(region_name=args.region)
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)[
        "Stacks"
    ][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise RuntimeError("Complete the deployment before running paid scenarios.")
    outputs = {v["OutputKey"]: v["OutputValue"] for v in stack["Outputs"]}
    parameters = {
        v["ParameterKey"]: v.get("ParameterValue", "") for v in stack["Parameters"]
    }
    owner = parameters["PaymentOwnerSub"]
    cognito = session.client("cognito-idp").admin_get_user(
        UserPoolId=outputs["UserPoolId"], Username=owner
    )
    if not cognito["Enabled"] or cognito["UserStatus"] != "CONFIRMED":
        raise RuntimeError("The configured wallet owner is not active.")
    settings = Settings(
        app_mode="aws",
        aws_region=args.region,
        payment_manager_arn=parameters["PaymentManagerArn"],
        payment_connector_id=parameters["PaymentConnectorId"],
        payment_instrument_id=parameters["PaymentInstrumentId"],
        payment_user_id=parameters["PaymentUserId"],
        payment_owner_sub=owner,
    )
    client = session.client(
        "bedrock-agentcore",
        config=Config(read_timeout=240, retries={"max_attempts": 0}),
    )
    control = session.client("bedrock-agentcore-control")
    wallet = inspect_existing_wallet(settings, client=client, control=control)
    if Decimal(wallet["balance"]) < cap:
        raise RuntimeError("The payer lacks enough test USDC for this run.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    journal_path = args.output_dir / "run.json"
    if args.initial_snapshot:
        if journal_path.exists():
            raise RuntimeError(
                "On resume, omit --initial-snapshot to read current AWS records."
            )
        before = json.loads(args.initial_snapshot.read_text())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(before["captured_at"])
        if age.total_seconds() > 1800:
            raise RuntimeError("The initial snapshot is stale.")
    else:
        before = snapshot(session, outputs, args.output_dir / "resume-snapshot.json")
    if before["user"]["id"] != owner or not before["user"]["wallet_connected"]:
        raise RuntimeError("Snapshot does not match the configured wallet owner.")
    journal = (
        json.loads(journal_path.read_text())
        if journal_path.exists()
        else {
            "name": fixtures["name"],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "owner_sub": owner,
            "payment_cap": str(cap),
            "wallet_before": wallet,
            "agents": {},
            "tasks": {},
            "receipts": {},
            "operations": [],
        }
    )
    if journal["owner_sub"] != owner:
        raise RuntimeError("This run belongs to another account.")
    fixture_hash = hashlib.sha256(
        json.dumps(fixtures, sort_keys=True).encode()
    ).hexdigest()
    if journal.get("fixtures_sha256", fixture_hash) != fixture_hash:
        raise RuntimeError(
            "Scenario definitions changed; use a separate output directory for a new run."
        )
    definitions = {task["key"]: task for task in fixtures["tasks"]}
    for key, saved in journal["tasks"].items():
        if key not in definitions or any(
            saved[field] != definitions[key][field]
            for field in ("title", "spec", "category", "budget")
        ):
            raise RuntimeError(
                "Existing run records do not match these scenario definitions."
            )
    journal["fixtures_sha256"] = fixture_hash

    def invoke(action, data=None, task_id=None):
        operation = {
            "action": action,
            "task_id": task_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "started",
        }
        journal["operations"].append(operation)
        write_json(journal_path, journal)
        print(
            f"{action}: {task_id or (data or {}).get('name') or (data or {}).get('title')}",
            flush=True,
        )
        try:
            response = client.invoke_agent_runtime(
                agentRuntimeArn=outputs["OrchestratorRuntimeArn"],
                runtimeSessionId=str(uuid4()),
                contentType="application/json",
                payload=json.dumps(
                    {
                        "action": action,
                        "user_id": owner,
                        "task_id": task_id,
                        "data": data or {},
                    }
                ).encode(),
            )
            result = json.loads(response["response"].read())
            if "error" in result:
                raise RuntimeError(result["error"])
            operation["status"] = "succeeded"
            operation["result_id"] = result.get("id")
            write_json(journal_path, journal)
            return result
        except Exception as exc:
            operation["status"] = "needs_inspection"
            operation["error"] = str(exc)
            write_json(journal_path, journal)
            raise

    # Resolve every receiving wallet under the same existing payment identity.
    for definition in fixtures["agents"]:
        instrument = client.get_payment_instrument(
            paymentManagerArn=settings.payment_manager_arn,
            userId=settings.payment_user_id,
            paymentInstrumentId=definition["recipient_instrument_id"],
        )["paymentInstrument"]
        recipient = instrument["paymentInstrumentDetails"]["embeddedCryptoWallet"][
            "walletAddress"
        ]
        if (
            instrument["status"] != "ACTIVE"
            or instrument["userId"] != settings.payment_user_id
            or recipient.lower() == wallet["address"].lower()
        ):
            raise RuntimeError("Invalid existing receiving wallet.")
        profile = {**definition["profile"], "wallet": recipient.lower()}
        existing = [
            a
            for a in before["agents"]
            if a["wallet"] and a["wallet"].lower() == recipient.lower()
        ]
        if existing:
            if (
                len(existing) != 1
                or existing[0]["name"] != profile["name"]
                or existing[0]["price"] != profile["price"]
            ):
                raise RuntimeError(
                    "A receiving wallet is assigned to a different profile."
                )
            agent = existing[0]
        else:
            agent = invoke("publish_agent", profile)
        journal["agents"][definition["key"]] = agent
        write_json(journal_path, journal)

    for definition in fixtures["tasks"]:
        existing = [t for t in before["tasks"] if t["title"] == definition["title"]]
        if len(existing) > 1:
            raise RuntimeError(
                "Duplicate scenario titles require inspection before continuing."
            )
        if existing:
            task = existing[0]
            if (
                task["spec"] != definition["spec"]
                or task["selection_mode"] != "auto"
                or task["budget"] != definition["budget"]
            ):
                raise RuntimeError(
                    "An existing task differs from the requested scenario."
                )
        else:
            data = {k: v for k, v in definition.items() if k != "key"}
            data.update(
                deadline=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                selection_mode="auto",
                agent_scope="live",
            )
            task = invoke("create_task", data)
        journal["tasks"][definition["key"]] = task
        write_json(journal_path, journal)
        if task["status"] in {"open", "bidding"}:
            task = invoke("quote_marketplace", task_id=task["id"])
            journal["tasks"][definition["key"]] = task
            write_json(journal_path, journal)
        winner = next(
            (a for a in journal["agents"].values() if a["id"] == task["winner_id"]),
            None,
        )
        if not winner or task["is_demo"]:
            raise RuntimeError(
                "Automatic bidding did not select an approved scenario agent."
            )
        print(
            f"Selected {winner['name']} for {definition['key']}: {task['selection_reason']}",
            flush=True,
        )

    for key, task in list(journal["tasks"].items()):
        winner = next(
            a for a in journal["agents"].values() if a["id"] == task["winner_id"]
        )
        if task["status"] == "awaiting_payment" and not task["payment"]:
            committed = sum(
                Decimal(item["payment"]["amount"])
                for item in journal["tasks"].values()
                if item.get("payment")
            )
            if committed + Decimal(winner["price"]) > cap:
                raise RuntimeError(
                    "This payment would exceed the run's total authorization."
                )
            task = invoke("process_payment", task_id=task["id"])
            journal["tasks"][key] = task
            write_json(journal_path, journal)
        payment = task.get("payment")
        if not payment or payment["status"] != "settled":
            raise RuntimeError(
                f"{key}: payment needs inspection; no automatic payment retry."
            )
        if Decimal(payment["amount"]) > Decimal(task["budget"]):
            raise RuntimeError("Payment exceeded the authorized task budget.")
        journal["receipts"][key] = verify_receipt(
            payment["transaction_hash"],
            wallet["address"],
            winner["wallet"],
            int(Decimal(payment["amount"]) * 1_000_000),
        )
        write_json(journal_path, journal)
        if task["status"] == "paid":
            task = invoke("settle_marketplace", task_id=task["id"])
            journal["tasks"][key] = task
            write_json(journal_path, journal)
        if task["status"] != "completed" or not task["delivery"]:
            raise RuntimeError(f"{key}: delivery is incomplete.")
        (args.output_dir / f"{key}.md").write_text(task["delivery"] + "\n")
        print(
            f"Completed {key}: {payment['amount']} test USDC, {payment['transaction_hash']}",
            flush=True,
        )

    after = snapshot(session, outputs, args.output_dir / "after.json")
    for task in journal["tasks"].values():
        saved = next(t for t in after["tasks"] if t["id"] == task["id"])
        if saved["status"] != "completed" or saved["delivery"] != task["delivery"]:
            raise RuntimeError("A completed deliverable was not persisted.")
    total = sum(Decimal(t["payment"]["amount"]) for t in journal["tasks"].values())
    if total > cap:
        raise RuntimeError("The scenario total exceeded the authorized cap.")
    journal.update(
        completed_at=datetime.now(timezone.utc).isoformat(),
        total_paid=str(total),
        wallet_after=inspect_existing_wallet(settings, client=client, control=control),
        database_verified=True,
    )
    write_json(journal_path, journal)
    print(
        f"All scenarios completed; total paid {total} test USDC. Results: {args.output_dir}",
        flush=True,
    )


if __name__ == "__main__":
    main()
