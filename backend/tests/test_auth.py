import time
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth


def test_aws_auth_requires_access_token_for_correct_client(client, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_test"
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            app_mode="aws", cognito_issuer=issuer, cognito_client_id="test-client"
        ),
    )
    monkeypatch.setattr(
        auth,
        "jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())
        ),
    )
    claims = {
        "iss": issuer,
        "sub": "verified-user",
        "exp": int(time.time()) + 3600,
        "token_use": "access",
        "client_id": "test-client",
        "username": "Test Builder",
    }

    def request(**overrides):
        token = jwt.encode({**claims, **overrides}, key, algorithm="RS256")
        return client.get(
            "/api/me",
            headers={"Authorization": f"Bearer {token}", "X-User-Id": "demo-user"},
        )

    assert client.get("/api/me").status_code == 401
    assert request(token_use="id").status_code == 401
    assert request(client_id="another-client").status_code == 401
    assert request(iss="https://attacker.example").status_code == 401
    assert request(exp=int(time.time()) - 1).status_code == 401
    response = request()
    assert response.status_code == 200
    assert response.json()["id"] == "verified-user"
    assert response.json()["id"] != "demo-user"
