"""Verify a browser-created automatic task and explicitly resume selected paid tasks.

Real Base Sepolia transfers can occur. All selected tasks must have budgets of
at most 0.01 USDC, and the total verification budget is capped at 0.03 USDC.
"""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time

import boto3
import httpx

from run_business_scenarios import verify_receipt, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--resume-task", action="append", default=[])
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[1] / "artifacts/automatic-workflow"
    created = json.loads((directory / "browser-create.json").read_text())
    assert created.get("browser_closed_at") and created["write_requests"] == [
        "/api/tasks"
    ]
    credentials = json.loads(args.credentials_file.read_text())
    session = boto3.Session(region_name="us-east-1")
    stack = session.client("cloudformation").describe_stacks(
        StackName="AgentMarketplace"
    )["Stacks"][0]
    assert stack["StackStatus"] == "UPDATE_COMPLETE"
    outputs = {v["OutputKey"]: v["OutputValue"] for v in stack["Outputs"]}
    parameters = {
        v["ParameterKey"]: v.get("ParameterValue", "") for v in stack["Parameters"]
    }
    assert credentials["sub"] == parameters["PaymentDelegateSub"]
    auth = session.client("cognito-idp").initiate_auth(
        ClientId=outputs["UserPoolClientId"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": credentials["email"],
            "PASSWORD": credentials["password"],
        },
    )
    task_ids = list(dict.fromkeys([created["task"]["id"], *args.resume_task]))
    report = {"task_ids": task_ids, "browser_closed": True, "tasks": {}, "receipts": {}}
    path = directory / "verification.json"
    with httpx.Client(
        base_url=outputs["WebsiteUrl"],
        timeout=45,
        headers={
            "Authorization": "Bearer " + auth["AuthenticationResult"]["AccessToken"]
        },
    ) as client:

        def get(endpoint):
            response = client.get("/api" + endpoint)
            response.raise_for_status()
            return response.json()

        tasks = [get("/tasks/" + task_id) for task_id in task_ids]
        assert sum(Decimal(t["budget"]) for t in tasks) <= Decimal("0.03")
        for task in tasks:
            assert not task["read_only"] and task["agent_scope"] == "live"
            assert task["selection_mode"] == "auto"
            assert Decimal(task["budget"]) <= Decimal("0.01")
        for task in tasks:
            if task["id"] in args.resume_task and task["status"] != "completed":
                response = client.post(
                    "/api/tasks/" + task["id"] + "/automate", json={}
                )
                response.raise_for_status()
        for _ in range(100):
            report["tasks"] = {
                task_id: get("/tasks/" + task_id) for task_id in task_ids
            }
            write_json(path, report)
            for task in report["tasks"].values():
                if task.get("automation") and task["automation"]["status"] in {
                    "blocked",
                    "review_required",
                }:
                    raise RuntimeError(
                        f"Task {task['id']} paused: {task['automation']['error']}"
                    )
            if all(t["status"] == "completed" for t in report["tasks"].values()):
                break
            time.sleep(3)
        else:
            raise RuntimeError(
                "Tasks are still running; inspect the saved states before retrying."
            )
        wallet = get("/me/wallet")
        for task in report["tasks"].values():
            assert task["automation"]["status"] == "completed"
            payment = task["payment"]
            assert payment["status"] == "settled" and payment["provider"] == "agentcore"
            assert Decimal(payment["amount"]) <= Decimal(task["budget"])
            winner = next(
                b for b in task["bids"] if b["agent"]["id"] == task["winner_id"]
            )
            assert not winner["agent"]["is_demo"] and winner["match_score"] >= 70
            report["receipts"][task["id"]] = verify_receipt(
                payment["transaction_hash"],
                wallet["address"],
                winner["agent"]["wallet"],
                int(Decimal(payment["amount"]) * 1_000_000),
            )
            assert task["delivery"]
            (directory / f"{task['id']}.md").write_text(task["delivery"] + "\n")
            task["delivery_sha256"] = hashlib.sha256(
                task["delivery"].encode()
            ).hexdigest()
            print(
                json.dumps(
                    {
                        "id": task["id"],
                        "title": task["title"],
                        "status": task["status"],
                        "agent": winner["agent"]["name"],
                        "amount": payment["amount"],
                        "transaction_hash": payment["transaction_hash"],
                    }
                ),
                flush=True,
            )
        report["account_after"] = get("/me")
        report["verified"] = True
        write_json(path, report)


if __name__ == "__main__":
    main()
