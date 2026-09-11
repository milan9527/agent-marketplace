"""Verify a demo account's real Cognito login and read-only shared AWS records."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import boto3
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--stack", default="AgentMarketplace")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/aws-demo-verification.json")
    )
    args = parser.parse_args()
    credentials = json.loads(args.credentials_file.read_text())
    session = boto3.Session(region_name=args.region)
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)[
        "Stacks"
    ][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise RuntimeError("Complete the showcase deployment before verification.")
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    parameters = {
        item["ParameterKey"]: item.get("ParameterValue", "")
        for item in stack["Parameters"]
    }
    assert credentials["sub"] == parameters["ShowcaseUserSub"]
    assert parameters["PaymentOwnerSub"] != credentials["sub"]
    cognito = session.client("cognito-idp")
    user = cognito.admin_get_user(
        UserPoolId=outputs["UserPoolId"], Username=credentials["email"]
    )
    assert user["Enabled"] and user["UserStatus"] == "CONFIRMED"
    pool = cognito.describe_user_pool(UserPoolId=outputs["UserPoolId"])["UserPool"]
    assert pool["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"]
    login = cognito.initiate_auth(
        ClientId=outputs["UserPoolClientId"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": credentials["email"],
            "PASSWORD": credentials["password"],
        },
    )
    token = login["AuthenticationResult"]["AccessToken"]
    task_ids = set(parameters["ShowcaseTaskIds"].split(","))
    agent_ids = set(parameters["ShowcaseAgentIds"].split(","))
    with httpx.Client(
        base_url=outputs["WebsiteUrl"],
        headers={"Authorization": f"Bearer {token}"},
        timeout=45,
    ) as client:

        def get(path):
            response = client.get("/api" + path)
            response.raise_for_status()
            return response.json()

        identity = get("/me")
        tasks = get("/tasks")
        agents = get("/agents")
        shared_agents = get("/agents?mine=true")
        payments = get("/payments")
        overview = get("/overview")
        assert identity["id"] == credentials["sub"]
        assert identity["name"] == "Marketplace Demo"
        delegated = parameters.get("PaymentDelegateSub") == credentials["sub"]
        assert identity["wallet_connected"] == delegated
        shared_tasks = [t for t in tasks if t["read_only"]]
        shared_payments = [p for p in payments if p["read_only"]]
        assert {t["id"] for t in shared_tasks} == task_ids
        assert all(
            t["read_only"] and t["status"] == "completed" and t["delivery"]
            for t in shared_tasks
        )
        assert {a["id"] for a in shared_agents} == agent_ids
        assert all(a["read_only"] for a in shared_agents)
        assert agent_ids <= {a["id"] for a in agents}
        assert sum(bool(a["is_demo"]) for a in agents) == 8
        assert len(shared_payments) == 3
        assert all(p["status"] == "settled" and p["transaction_hash"] for p in shared_payments)
        assert overview["tasks"] == len(tasks)
        assert overview["completed"] == sum(t["status"] == "completed" for t in tasks)
        assert overview["spent"] == identity["spent"]
        for task in shared_tasks:
            detail = get("/tasks/" + task["id"])
            assert detail["delivery"] == task["delivery"] and detail["read_only"]
        # Existing settled/completed records make these negative authorization
        # probes safe even if an unexpected response bypasses the read-only gate.
        selected = next(t for t in shared_tasks if t["payment"])
        denied = {}
        for action in ("pay", "deliver"):
            response = client.post(f"/api/tasks/{selected['id']}/{action}", json={})
            denied[action] = response.status_code
            assert response.status_code == 403
        wallet_response = client.get("/api/me/wallet")
        assert wallet_response.status_code == (200 if delegated else 403)
        if delegated:
            assert wallet_response.json()["status"] == "ACTIVE"
            assert identity["wallet_shared"]
            assert wallet_response.json()["connector_id"] == parameters["PaymentConnectorId"]
        else:
            denied["wallet_read"] = wallet_response.status_code
        assert client.get(f"/api/tasks/{uuid4()}").status_code == 404
        assert get("/me")["spent"] == identity["spent"]
    report = {
        "email": credentials["email"],
        "sub": credentials["sub"],
        "login_verified": True,
        "shared_task_count": len(shared_tasks),
        "visible_task_count": len(tasks),
        "visible_agent_count": len(agents),
        "shared_business_agent_count": len(shared_agents),
        "shared_payment_count": len(shared_payments),
        "visible_payment_count": len(payments),
        "own_settled_payment_count": sum(
            not p["read_only"] and p["status"] == "settled" for p in payments
        ),
        "self_registration_enabled": False,
        "wallet_connected": identity["wallet_connected"],
        "payment_delegate": delegated,
        "payment_limit": identity.get("payment_limit"),
        "spending": identity["spent"],
        "denied_actions": denied,
        "tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "bid_count": len(t["bids"]),
                "read_only": t["read_only"],
                "delivery_sha256": hashlib.sha256(t["delivery"].encode()).hexdigest(),
            }
            for t in shared_tasks
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
