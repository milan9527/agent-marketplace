"""Verify a manual start hands real tool execution to the worker without a payment."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

import boto3
import httpx

from run_business_scenarios import write_json

TITLE = "Tool proof | Manual order-status template"
SPEC = (
    "Create a short English customer-facing Markdown order-status template for fictional shop "
    "BrightCart. Supplied facts: order BC-100, status Packed, next update within one business day. "
    "Save the finished template as order_status.md. Do not invent shipping dates or tracking details. "
    "This task creates a downloadable file only; do not send an email or update an order."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", type=Path, required=True)
    args = parser.parse_args()
    credentials = json.loads(args.credentials_file.read_text())
    directory = Path("artifacts/real-agent-tools")
    path = directory / "manual-verification.json"
    journal = json.loads(path.read_text()) if path.exists() else {}
    journal.pop("verified", None)
    session = boto3.Session(region_name="us-east-1")
    stack = session.client("cloudformation").describe_stacks(
        StackName="AgentMarketplace"
    )["Stacks"][0]
    assert stack["StackStatus"] == "UPDATE_COMPLETE"
    outputs = {v["OutputKey"]: v["OutputValue"] for v in stack["Outputs"]}
    runtime = session.client("bedrock-agentcore-control").get_agent_runtime(
        agentRuntimeId=outputs["OrchestratorRuntimeArn"].rsplit("/", 1)[-1]
    )
    journal["runtime_version"] = runtime["agentRuntimeVersion"]
    journal["runtime_image"] = runtime["agentRuntimeArtifact"][
        "containerConfiguration"
    ]["containerUri"]
    login = session.client("cognito-idp").initiate_auth(
        ClientId=outputs["UserPoolClientId"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": credentials["email"],
            "PASSWORD": credentials["password"],
        },
    )
    with httpx.Client(
        base_url=outputs["WebsiteUrl"],
        timeout=180,
        headers={
            "Authorization": "Bearer " + login["AuthenticationResult"]["AccessToken"]
        },
    ) as client:

        def get(endpoint):
            response = client.get("/api" + endpoint)
            response.raise_for_status()
            return response.json()

        def post(endpoint, body):
            response = client.post("/api" + endpoint, json=body)
            response.raise_for_status()
            return response.json()

        journal.setdefault("account_before", get("/me"))
        journal.setdefault("payments_before", get("/payments"))
        matches = [
            t for t in get("/tasks") if t["title"] == TITLE and not t["read_only"]
        ]
        if matches:
            assert len(matches) == 1 and matches[0]["spec"] == SPEC
            task = matches[0]
        else:
            assert not journal.get("create_requested"), (
                "Inspect the earlier create request."
            )
            journal["create_requested"] = True
            write_json(path, journal)
            task = post(
                "/tasks",
                {
                    "title": TITLE,
                    "spec": SPEC,
                    "category": "Content",
                    "budget": "0.05",
                    "agent_scope": "demo",
                    "preferred_agent_id": "demo-quill",
                    "selection_mode": "manual",
                    "auto_execute": False,
                    "deadline": (
                        datetime.now(timezone.utc) + timedelta(days=2)
                    ).isoformat(),
                },
            )
        endpoint = "/tasks/" + task["id"]
        if task["status"] == "open":
            task = post(endpoint + "/quote", {})
        if task["status"] == "bidding":
            assert len(task["bids"]) == 1
            task = post(endpoint + "/select", {"bid_id": task["bids"][0]["id"]})
        if task["status"] == "demo_ready":
            assert not journal.get("deliver_requested"), (
                "Inspect the earlier delivery request."
            )
            assert task["automation"] is None
            journal["manual_start_before"] = task
            journal["deliver_requested"] = True
            write_json(path, journal)
            task = post(endpoint + "/deliver", {})
            journal["manual_start_after"] = task
            write_json(path, journal)
            assert task["status"] in {"executing", "completed"}
            assert task["automation"]["status"] in {"queued", "running", "completed"}
        if journal.get("deliver_requested") and task["status"] in {
            "executing",
            "completed",
        }:
            response = client.post("/api" + endpoint + "/deliver", json={})
            assert response.status_code in {200, 409}, response.text
            if response.status_code == 409:
                assert response.json()["detail"] == (
                    "This task is running automatically. Its progress will update shortly."
                )
                repeated = get(endpoint)
            else:
                repeated = response.json()
            assert repeated["execution"]["id"] == task["execution"]["id"]
            journal["repeated_request"] = {
                "status_code": response.status_code,
                "task": repeated,
            }
            write_json(path, journal)
        for _ in range(200):
            task = get(endpoint)
            journal["task"] = task
            write_json(path, journal)
            if task["status"] in {"completed", "execution_blocked"}:
                break
            assert (task.get("automation") or {}).get("status") != "review_required"
            time.sleep(3)
        assert (
            task["status"] == "completed" and task["execution"]["validation"]["passed"]
        )
        assert task["payment"] is None and task["automation"]["status"] == "completed"
        file = get(f"{endpoint}/artifacts/{task['execution']['id']}/order_status.md")
        metadata = next(
            a for a in task["execution"]["artifacts"] if a["name"] == file["name"]
        )
        assert (
            hashlib.sha256(file["content"].encode()).hexdigest() == metadata["sha256"]
        )
        assert "BC-100" in file["content"] and "packed" in file["content"].lower()
        (directory / "manual-order-status.md").write_text(file["content"])
        journal["account_after"], journal["payments_after"] = (
            get("/me"),
            get("/payments"),
        )
        assert journal["account_after"]["spent"] == journal["account_before"]["spent"]
        assert {p["id"] for p in journal["payments_after"]} == {
            p["id"] for p in journal["payments_before"]
        }
        journal["verified"] = True
        write_json(path, journal)
        print(
            "Manual start, repeated delivery, background completion, and download passed; no payment."
        )


if __name__ == "__main__":
    main()
