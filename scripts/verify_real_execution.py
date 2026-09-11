"""Verify real tool execution across six categories without new wallet payments."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

import boto3
import httpx

from run_business_scenarios import write_json

EXISTING = {
    "research": "d1cf7813-81ed-4a89-a17b-f5851a45f042",
    "finance": "156a6ffd-bb7d-4efa-af21-bdd6c6f429cb",
    "data": "89d36985-ffd1-44a4-9d4e-128b64ad1320",
    "automation": "46f81c67-daf0-4a7d-a395-b91d70e1e378",
}
NEW_TASKS = {
    "development": {
        "title": "Tool proof | Tested order aggregation",
        "category": "Development",
        "preferred_agent_id": "demo-codecraft",
        "spec": (
            "Implement Python summarize_orders(rows), returning a dict of total quantity per SKU. "
            "Input rows contain sku (nonempty string) and quantity (nonnegative integer; reject booleans). "
            "Reject invalid rows with ValueError, including non-dictionary rows such as None. "
            "Execute meaningful tests for empty input, duplicate SKUs, non-dictionary rows, "
            "zero quantity, negative quantity, and invalid SKU. Example A:2, B:1, A:3 must yield A:5, B:1. "
            "Use the isolated code tool to actually run the implementation and tests, and print test outcomes. "
            "Save implementation.py and tests.py as downloadable files. Return an English result explaining "
            "what ran and any limitations. No external systems or package installation are needed."
        ),
    },
    "content": {
        "title": "Tool proof | Finished LumaDesk product page",
        "category": "Content",
        "preferred_agent_id": "demo-quill",
        "spec": (
            "Create a finished English Markdown product page for the fictional LumaDesk desk lamp using "
            "only these supplied facts: dimmable warm/cool lighting, USB-C power, physical control dial, "
            "no Wi-Fi, list price USD 49. Include a headline, short introduction, three benefit bullets, "
            "two FAQs and two email subject lines. Do not invent battery life, certifications, app control, "
            "reviews, discounts or market statistics. Actually save the finished content as lumadesk.md. "
            "This task creates a content file only; do not publish a website or send emails."
        ),
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", type=Path, required=True)
    args = parser.parse_args()
    directory = Path("artifacts/real-agent-tools")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "live-verification.json"
    journal = (
        json.loads(path.read_text()) if path.exists() else {"tasks": {}, "requests": {}}
    )
    journal.pop("verified", None)
    credentials = json.loads(args.credentials_file.read_text())
    session = boto3.Session(region_name="us-east-1")
    stack = session.client("cloudformation").describe_stacks(
        StackName="AgentMarketplace"
    )["Stacks"][0]
    assert stack["StackStatus"] == "UPDATE_COMPLETE"
    outputs = {v["OutputKey"]: v["OutputValue"] for v in stack["Outputs"]}
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
        timeout=120,
        headers={
            "Authorization": "Bearer " + login["AuthenticationResult"]["AccessToken"]
        },
    ) as client:

        def get(endpoint):
            response = client.get("/api" + endpoint)
            response.raise_for_status()
            return response.json()

        def post(endpoint, data):
            response = client.post("/api" + endpoint, json=data)
            response.raise_for_status()
            return response.json()

        account = get("/me")
        assert account["id"] == credentials["sub"]
        journal.setdefault("account_before", account)
        journal.setdefault("payments_before", get("/payments"))
        write_json(path, journal)
        for category, task_id in EXISTING.items():
            task = get("/tasks/" + task_id)
            assert not task["read_only"]
            if task["payment"]:
                assert task["payment"]["status"] == "settled"
            journal.setdefault("originals", {}).setdefault(category, task)
            request = journal["requests"].get(category)
            if request is None:
                assert task["status"] == "completed"
                journal["requests"][category] = {
                    "action": "rerun",
                    "previous_run": (task.get("execution") or {}).get("id"),
                    "task_id": task_id,
                }
                write_json(path, journal)
                task = post("/tasks/" + task_id + "/rerun", {})
            else:
                if (task.get("execution") or {}).get("id") == request["previous_run"]:
                    raise RuntimeError(
                        "Inspect the earlier rerun request before retrying it."
                    )
            journal["tasks"][category] = task
            write_json(path, journal)
        for category, data in NEW_TASKS.items():
            matches = [
                t
                for t in get("/tasks")
                if t["title"] == data["title"] and not t["read_only"]
            ]
            if matches:
                assert len(matches) == 1
                task = matches[0]
            else:
                if category in journal["requests"]:
                    raise RuntimeError(
                        "An earlier create request is uncertain; inspect it before retrying."
                    )
                journal["requests"][category] = {
                    "action": "create",
                    "title": data["title"],
                }
                write_json(path, journal)
                task = post(
                    "/tasks",
                    {
                        **data,
                        "budget": "0.05",
                        "agent_scope": "demo",
                        "selection_mode": "auto",
                        "auto_execute": True,
                        "deadline": (
                            datetime.now(timezone.utc) + timedelta(days=2)
                        ).isoformat(),
                    },
                )
            journal["tasks"][category] = task
            write_json(path, journal)
        previous = {}
        for _ in range(500):
            for category, old in list(journal["tasks"].items()):
                task = get("/tasks/" + old["id"])
                journal["tasks"][category] = task
                execution = task.get("execution") or {}
                status = (
                    task["status"],
                    execution.get("steps"),
                    execution.get("status"),
                )
                if previous.get(category) != status:
                    print(
                        json.dumps(
                            {
                                "category": category,
                                "task_id": task["id"],
                                "status": task["status"],
                                "steps": execution.get("steps"),
                                "execution": execution.get("status"),
                                "error": execution.get("error"),
                            }
                        ),
                        flush=True,
                    )
                    previous[category] = status
            write_json(path, journal)
            if all(
                t["status"] in {"completed", "execution_blocked"}
                or (t.get("automation") or {}).get("status")
                in {"blocked", "review_required"}
                for t in journal["tasks"].values()
            ):
                break
            time.sleep(3)
        for category, task in journal["tasks"].items():
            execution = task.get("execution") or {}
            if task["status"] != "completed":
                raise RuntimeError(
                    f"{category} did not complete: {execution.get('error') or task.get('selection_reason')}"
                )
            assert (
                execution["status"] == "completed" and execution["validation"]["passed"]
            )
            good = [t for t in execution["trace"] if t["status"] == "succeeded"]
            assert good and execution["artifacts"]
            if category == "research":
                assert any(t["tool"] == "web_search" for t in good)
                assert sum(t["tool"] == "read_page" for t in good) >= 2
            if category in {"finance", "data", "automation", "development"}:
                assert any(
                    t["tool"] == "run_code" and t["output"]["exit_code"] == 0
                    for t in good
                )
            original = journal.get("originals", {}).get(category)
            assert (
                task["payment"] == original["payment"]
                if original
                else task["payment"] is None
            )
            folder = directory / category
            folder.mkdir(exist_ok=True)
            (folder / "delivery.md").write_text(task["delivery"])
            for metadata in execution["artifacts"]:
                file = get(
                    f"/tasks/{task['id']}/artifacts/{execution['id']}/{metadata['name']}"
                )
                assert (
                    hashlib.sha256(file["content"].encode()).hexdigest()
                    == metadata["sha256"]
                )
                (folder / metadata["name"]).write_text(file["content"])
        journal["payments_after"] = get("/payments")
        journal["account_after"] = get("/me")
        assert {p["id"] for p in journal["payments_after"]} == {
            p["id"] for p in journal["payments_before"]
        }
        assert journal["account_after"]["spent"] == journal["account_before"]["spent"]
        journal["verified"] = True
        write_json(path, journal)
        print(
            "All six categories completed with tool evidence; no new wallet payments.",
            flush=True,
        )


if __name__ == "__main__":
    main()
