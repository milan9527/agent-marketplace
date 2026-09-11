"""Initialize shared demo profiles in RDS using a private, one-off Fargate task."""

import argparse
import time

import boto3

parser = argparse.ArgumentParser()
parser.add_argument("--stack", default="AgentMarketplace")
parser.add_argument("--region", default="us-east-1")
args = parser.parse_args()
session = boto3.Session(region_name=args.region)
outputs = session.client("cloudformation").describe_stacks(StackName=args.stack)[
    "Stacks"
][0]["Outputs"]
values = {item["OutputKey"]: item["OutputValue"] for item in outputs}
ecs = session.client("ecs")
response = ecs.run_task(
    cluster=values["MigrationCluster"],
    taskDefinition=values["MigrationTaskDefinition"],
    launchType="FARGATE",
    networkConfiguration={
        "awsvpcConfiguration": {
            "subnets": [values["MigrationSubnet"]],
            "securityGroups": [values["MigrationSecurityGroup"]],
            "assignPublicIp": "DISABLED",
        }
    },
    overrides={
        "containerOverrides": [{"name": "api", "command": ["python", "-m", "app.seed"]}]
    },
)
if response.get("failures") or not response.get("tasks"):
    raise SystemExit("Could not start catalog initialization; inspect ECS task events.")
task_arn = response["tasks"][0]["taskArn"]
print("Catalog initialization task:", task_arn, flush=True)
for _ in range(120):
    task = ecs.describe_tasks(cluster=values["MigrationCluster"], tasks=[task_arn])[
        "tasks"
    ][0]
    if task["lastStatus"] == "STOPPED":
        container = next(c for c in task["containers"] if c["name"] == "api")
        if container.get("exitCode") != 0:
            raise SystemExit(
                "Catalog initialization failed; inspect the task's CloudWatch logs."
            )
        print(
            "Shared demo catalog initialized. Existing profiles and user records were preserved."
        )
        break
    time.sleep(5)
else:
    raise SystemExit(
        "Initialization is still running. Inspect the task before retrying."
    )
