"""Save reviewed deliverables for completed, paid tasks without changing payments."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import time
import zlib

import boto3

REMOTE_CODE = """
import base64, hashlib, json, os, zlib
from datetime import datetime, timezone
from sqlalchemy import select
from app.config import get_settings
from app.db import session_factory
from app.main import me
from app.models import Agent, Payment, Task, User
from app.service import agent_view, record, task_view
payload = json.loads(zlib.decompress(base64.b64decode(os.environ["REVIEW_PAYLOAD"])))
s = get_settings()
assert s.app_mode == "aws" and s.payment_owner_sub == payload["owner_sub"]
owner = s.payment_owner_sub
with session_factory()() as db:
    user = db.get(User, owner)
    budget = (user.budget_micros, user.spent_micros, user.reserved_micros)
    payment_ids = list(db.scalars(select(Payment.id).where(Payment.owner_id == owner).order_by(Payment.id)))
    agent_counts = dict(db.execute(select(Agent.id, Agent.completed_tasks).where(Agent.owner_id == owner)).all())
    updated = []
    for revision in payload["revisions"]:
        task = db.scalar(select(Task).where(Task.id == revision["task_id"], Task.owner_id == owner).with_for_update())
        assert task is not None and task.status == "completed"
        payment = db.scalar(select(Payment).where(Payment.task_id == task.id))
        assert payment is not None and payment.status == "settled"
        old_hash = hashlib.sha256(task.delivery.encode()).hexdigest()
        new_hash = hashlib.sha256(revision["delivery"].encode()).hexdigest()
        if old_hash != new_hash:
            assert old_hash == revision["original_sha256"], "Delivery changed since review started."
            task.delivery = revision["delivery"]
            record(db, owner, "delivery_revised", revision["reason"], task.id)
        updated.append({"task_id": task.id, "delivery_sha256": new_hash})
    db.commit()
with session_factory()() as db:
    user = db.get(User, owner)
    assert (user.budget_micros, user.spent_micros, user.reserved_micros) == budget
    assert list(db.scalars(select(Payment.id).where(Payment.owner_id == owner).order_by(Payment.id))) == payment_ids
    assert dict(db.execute(select(Agent.id, Agent.completed_tasks).where(Agent.owner_id == owner)).all()) == agent_counts
    for item in updated:
        assert hashlib.sha256(db.get(Task, item["task_id"]).delivery.encode()).hexdigest() == item["delivery_sha256"]
    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(), "updated": updated,
        "spending_unchanged": True, "payment_records_unchanged": True,
        "completion_counts_unchanged": True, "user": me(user=user),
        "agents": [agent_view(a) for a in db.scalars(select(Agent).where(Agent.owner_id == owner))],
        "tasks": [task_view(t, db) for t in db.scalars(select(Task).where(Task.owner_id == owner))],
        "payments": [
            {k: getattr(p, k) for k in ("id", "task_id", "status", "session_id", "process_id",
                "amount_micros", "transaction_hash", "error")}
            for p in db.scalars(select(Payment).where(Payment.owner_id == owner))
        ],
    }
print("REVIEW_RESULT " + json.dumps(report, default=str), flush=True)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--stack", default="AgentMarketplace")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    revisions = json.loads(args.manifest.read_text())
    for revision in revisions:
        revision["delivery"] = (
            (args.manifest.parent / revision.pop("delivery_file")).read_text().rstrip()
        )
        if not revision["delivery"] or len(revision["delivery"]) > 100000:
            raise RuntimeError("A reviewed deliverable is empty or too large.")
    session = boto3.Session(region_name=args.region)
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)[
        "Stacks"
    ][0]
    outputs = {v["OutputKey"]: v["OutputValue"] for v in stack["Outputs"]}
    parameters = {
        v["ParameterKey"]: v.get("ParameterValue", "") for v in stack["Parameters"]
    }
    payload = {"owner_sub": parameters["PaymentOwnerSub"], "revisions": revisions}
    encoded = base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
    overrides = {
        "containerOverrides": [
            {
                "name": "api",
                "command": ["python", "-c", REMOTE_CODE],
                "environment": [{"name": "REVIEW_PAYLOAD", "value": encoded}],
            }
        ]
    }
    if len(json.dumps(overrides).encode()) > 8192:
        raise RuntimeError(
            "Reviewed documents exceed the ECS override limit; split the manifest."
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
        overrides=overrides,
    )
    if response.get("failures") or not response.get("tasks"):
        raise RuntimeError("Could not start the review update task.")
    arn = response["tasks"][0]["taskArn"]
    print("Reviewed-delivery update:", arn, flush=True)
    for _ in range(120):
        task = ecs.describe_tasks(cluster=outputs["MigrationCluster"], tasks=[arn])[
            "tasks"
        ][0]
        if task["lastStatus"] == "STOPPED":
            if (
                next(c for c in task["containers"] if c["name"] == "api").get(
                    "exitCode"
                )
                != 0
            ):
                raise RuntimeError(
                    "Review update failed; inspect the task's CloudWatch logs."
                )
            break
        time.sleep(5)
    else:
        raise RuntimeError("Review update is still running; inspect the task.")
    logs = session.client("logs")
    for _ in range(6):
        events = logs.get_log_events(
            logGroupName=logging["awslogs-group"],
            logStreamName=f"{logging['awslogs-stream-prefix']}/api/{arn.rsplit('/', 1)[-1]}",
            startFromHead=True,
        )["events"]
        for event in events:
            if event["message"].startswith("REVIEW_RESULT "):
                result = json.loads(event["message"].split(" ", 1)[1])
                expected = {
                    r["task_id"]: hashlib.sha256(r["delivery"].encode()).hexdigest()
                    for r in revisions
                }
                assert all(
                    expected[item["task_id"]] == item["delivery_sha256"]
                    for item in result["updated"]
                )
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2) + "\n")
                print(
                    json.dumps(
                        {
                            "updated": result["updated"],
                            "spending_unchanged": result["spending_unchanged"],
                        }
                    )
                )
                return
        time.sleep(2)
    raise RuntimeError("The review report is not yet available in CloudWatch.")


if __name__ == "__main__":
    main()
