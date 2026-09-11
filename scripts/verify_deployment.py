"""Read-only checks for the deployed website, private AWS resources, and authentication."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--stack", default="AgentMarketplace")
parser.add_argument("--region", default="us-east-1")
parser.add_argument("--output", default="artifacts/aws-verification.json")
args = parser.parse_args()
session = boto3.Session(region_name=args.region)
cf = session.client("cloudformation")
stack = cf.describe_stacks(StackName=args.stack)["Stacks"][0]
assert stack["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}, stack[
    "StackStatus"
]
values = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
checks = []


def passed(message):
    checks.append(message)
    print(f"PASS: {message}", flush=True)


with httpx.Client(base_url=values["WebsiteUrl"], timeout=30) as client:
    response = client.get("/login")
    assert response.status_code == 200 and '<div id="root">' in response.text
    assert client.get("/api/health").json() == {"status": "healthy"}
    config = client.get("/api/config").json()
    assert config["mode"] == "aws"
    assert config["cognito_client_id"] == values["UserPoolClientId"]
    assert client.get("/api/me").status_code == 401
passed(
    "Public HTTPS login, database health, Cognito configuration, and anonymous API rejection"
)

cognito = session.client("cognito-idp")
pool = cognito.describe_user_pool(UserPoolId=values["UserPoolId"])["UserPool"]
assert pool.get("AdminCreateUserConfig", {}).get(
    "AllowAdminCreateUserOnly", False
), "Cognito self-service registration must be disabled"
assert "email" in pool.get("AutoVerifiedAttributes", [])
app_client = cognito.describe_user_pool_client(
    UserPoolId=values["UserPoolId"], ClientId=values["UserPoolClientId"]
)["UserPoolClient"]
assert "ALLOW_USER_PASSWORD_AUTH" in app_client["ExplicitAuthFlows"]
passed(
    "Cognito self-service registration is disabled; email verification and password login remain configured"
)

cloudfront = session.client("cloudfront")
distribution = cloudfront.get_distribution(Id=values["CloudFrontDistributionId"])[
    "Distribution"
]
assert distribution["Status"] == "Deployed"
origins = distribution["DistributionConfig"]["Origins"]["Items"]
s3_origin = next(o for o in origins if o.get("OriginAccessControlId"))
oac = cloudfront.get_origin_access_control(Id=s3_origin["OriginAccessControlId"])[
    "OriginAccessControl"
]["OriginAccessControlConfig"]
assert oac["SigningBehavior"] == "always" and oac["SigningProtocol"] == "sigv4"
vpc_origin = next(o for o in origins if o.get("VpcOriginConfig"))
endpoint = cloudfront.get_vpc_origin(Id=vpc_origin["VpcOriginConfig"]["VpcOriginId"])[
    "VpcOrigin"
]["VpcOriginEndpointConfig"]
assert endpoint["OriginProtocolPolicy"] == "http-only" and endpoint["HTTPPort"] == 80
passed("CloudFront is deployed with S3 OAC and the private API origin on HTTP/80")

s3 = session.client("s3")
bucket = values["FrontendBucket"]
assert all(
    s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"].values()
)
policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
allow = [rule for rule in policy["Statement"] if rule["Effect"] == "Allow"]
assert len(allow) == 1 and allow[0]["Principal"] == {
    "Service": "cloudfront.amazonaws.com"
}
assert allow[0]["Condition"]["StringEquals"]["AWS:SourceArn"] == distribution["ARN"]
assert (
    httpx.get(
        f"https://{bucket}.s3.{args.region}.amazonaws.com/index.html", timeout=30
    ).status_code
    == 403
)
passed("S3 blocks public access and grants reads only to this CloudFront distribution")

service = session.client("ecs").describe_services(
    cluster=values["MigrationCluster"], services=[values["ApiServiceName"]]
)["services"][0]
assert (
    service["runningCount"] == service["desiredCount"] and service["runningCount"] > 0
)
assert service["pendingCount"] == 0
assert (
    service["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"]
    == "DISABLED"
)
passed("ECS has its desired running capacity and no public task IP")

worker = session.client("ecs").describe_services(
    cluster=values["MigrationCluster"], services=[values["WorkflowWorkerServiceName"]]
)["services"][0]
assert worker["runningCount"] == worker["desiredCount"] == 1
assert worker["pendingCount"] == 0
assert worker["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"
passed("The automatic-workflow worker is running in a private ECS task")

resources = cf.list_stack_resources(StackName=args.stack)["StackResourceSummaries"]
db_id = next(
    r["PhysicalResourceId"]
    for r in resources
    if r["ResourceType"] == "AWS::RDS::DBInstance"
)
database = session.client("rds").describe_db_instances(DBInstanceIdentifier=db_id)[
    "DBInstances"
][0]
assert database["DBInstanceStatus"] == "available"
assert database["StorageEncrypted"] and not database["PubliclyAccessible"]
passed("RDS is available, encrypted, and private")

control = session.client("bedrock-agentcore-control")
for key in ("OrchestratorRuntimeArn", "BidderRuntimeArn"):
    runtime = control.get_agent_runtime(agentRuntimeId=values[key].rsplit("/", 1)[1])
    assert runtime["status"] == "READY", runtime["status"]
passed("Both AgentCore Runtimes are ready")

output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps(
        {
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "region": args.region,
            "website": values["WebsiteUrl"],
            "login": values["LoginUrl"],
            "checks": checks,
            "payment_tested": False,
        },
        indent=2,
    )
    + "\n"
)
print(f"Report: {output}")
