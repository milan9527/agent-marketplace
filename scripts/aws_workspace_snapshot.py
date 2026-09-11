"""Read the configured wallet owner's marketplace records through a private ECS task."""

import argparse
import json
from pathlib import Path
import time

import boto3

REMOTE_CODE = """
import json
from datetime import datetime, timezone
from sqlalchemy import select
from app.config import get_settings
from app.db import session_factory
from app.main import me
from app.models import Agent, Payment, Task, User
from app.service import agent_view, task_view
s = get_settings()
assert s.app_mode == "aws" and s.payment_owner_sub
with session_factory()() as db:
    user = db.get(User, s.payment_owner_sub)
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "user": me(user=user),
        "agents": [agent_view(a) for a in db.scalars(select(Agent).where(Agent.owner_id == user.id))],
        "tasks": [task_view(t, db) for t in db.scalars(select(Task).where(Task.owner_id == user.id))],
        "payments": [
            {k: getattr(p, k) for k in ("id", "task_id", "status", "session_id", "process_id",
              "amount_micros", "transaction_hash", "error")}
            for p in db.scalars(select(Payment).where(Payment.owner_id == user.id))
        ],
    }
print("WORKSPACE_SNAPSHOT " + json.dumps(result, default=str), flush=True)
"""


def snapshot(session, outputs, path):
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
                {"name": "api", "command": ["python", "-c", REMOTE_CODE]}
            ]
        },
    )
    if response.get("failures") or not response.get("tasks"):
        raise RuntimeError("Could not start the workspace snapshot task.")
    arn = response["tasks"][0]["taskArn"]
    print(f"Read-only workspace snapshot: {arn}", flush=True)
    for _ in range(120):
        task = ecs.describe_tasks(cluster=outputs["MigrationCluster"], tasks=[arn])[
            "tasks"
        ][0]
        if task["lastStatus"] == "STOPPED":
            result = next(c for c in task["containers"] if c["name"] == "api")
            if result.get("exitCode") != 0:
                raise RuntimeError(
                    "Snapshot failed; inspect the task's CloudWatch logs."
                )
            break
        time.sleep(5)
    else:
        raise RuntimeError("Snapshot task is still running.")
    logs = session.client("logs")
    stream = f"{logging['awslogs-stream-prefix']}/api/{arn.rsplit('/', 1)[-1]}"
    for _ in range(6):
        events = logs.get_log_events(
            logGroupName=logging["awslogs-group"],
            logStreamName=stream,
            startFromHead=True,
        )["events"]
        for event in events:
            if event["message"].startswith("WORKSPACE_SNAPSHOT "):
                data = json.loads(event["message"].split(" ", 1)[1])
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, indent=2) + "\n")
                return data
        time.sleep(2)
    raise RuntimeError("Snapshot report is not yet available in CloudWatch.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="AgentMarketplace")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", default="artifacts/aws-workspace-snapshot.json")
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)[
        "Stacks"
    ][0]
    outputs = {v["OutputKey"]: v["OutputValue"] for v in stack["Outputs"]}
    data = snapshot(session, outputs, args.output)
    print(
        json.dumps(
            {
                "user": data["user"],
                "agents": len(data["agents"]),
                "tasks": len(data["tasks"]),
                "payments": len(data["payments"]),
            }
        )
    )


if __name__ == "__main__":
    main()
