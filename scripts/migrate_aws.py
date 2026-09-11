"""Run the database migration as a one-off Fargate task inside the database VPC."""

import argparse
import json
from pathlib import Path
import time

import boto3

parser = argparse.ArgumentParser()
parser.add_argument("--stack", default="AgentMarketplace")
parser.add_argument("--region", default="us-east-1")
parser.add_argument(
    "--include-migration",
    action="append",
    default=[],
    help="Copy a local migration into the current ECS image before upgrading; use for additive pre-deploy migrations.",
)
args = parser.parse_args()
command = ["alembic", "upgrade", "head"]
if args.include_migration:
    root = Path(__file__).resolve().parents[1] / "backend/migrations/versions"
    files = {}
    for filename in args.include_migration:
        path = Path(filename).resolve()
        if path.parent != root or path.suffix != ".py":
            raise SystemExit(
                "Included migrations must be Python files in backend/migrations/versions."
            )
        files[path.name] = path.read_text()
    code = (
        "from pathlib import Path\nimport subprocess\n"
        f"files={files!r}\n"
        "for name,content in files.items():\n"
        " p=Path('migrations/versions')/name\n"
        " if p.exists() and p.read_text()!=content: raise RuntimeError('Refusing to replace an existing migration')\n"
        " p.write_text(content)\n"
        "subprocess.run(['alembic','upgrade','head'],check=True)\n"
    )
    command = ["python", "-c", code]
overrides = {"containerOverrides": [{"name": "api", "command": command}]}
if len(json.dumps(overrides)) > 8192:
    raise SystemExit(
        "Migration bundle exceeds the ECS override limit; use a migration image."
    )
session = boto3.Session(region_name=args.region)
outputs = session.client("cloudformation").describe_stacks(StackName=args.stack)[
    "Stacks"
][0]["Outputs"]
values = {o["OutputKey"]: o["OutputValue"] for o in outputs}
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
    overrides=overrides,
)
if response.get("failures") or not response.get("tasks"):
    raise SystemExit("Could not start the migration task; inspect ECS task events.")
task_arn = response["tasks"][0]["taskArn"]
print("Migration task started:", task_arn)
for _ in range(120):
    task = ecs.describe_tasks(cluster=values["MigrationCluster"], tasks=[task_arn])[
        "tasks"
    ][0]
    if task["lastStatus"] == "STOPPED":
        container = next(c for c in task["containers"] if c["name"] == "api")
        if container.get("exitCode") != 0:
            raise SystemExit(
                "Migration failed; inspect marketplace-api CloudWatch logs."
            )
        print("Database migration completed.")
        break
    time.sleep(5)
else:
    raise SystemExit("Migration has not stopped yet. Inspect the task before retrying.")
