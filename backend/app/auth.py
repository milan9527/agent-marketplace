from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)


@lru_cache
def jwks_client():
    return jwt.PyJWKClient(f"{get_settings().cognito_issuer}/.well-known/jwks.json")


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()
    if settings.app_mode == "demo":
        user_id, name = "demo-user", "Alex Chen"
    else:
        if not credentials:
            raise HTTPException(
                401, "Please sign in", headers={"WWW-Authenticate": "Bearer"}
            )
        try:
            token = credentials.credentials
            key = jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=settings.cognito_issuer,
                options={
                    "verify_aud": False,
                    "require": ["exp", "sub", "iss", "token_use"],
                },
            )
            if (
                claims["token_use"] != "access"
                or claims.get("client_id") != settings.cognito_client_id
            ):
                raise jwt.InvalidTokenError()
            user_id, name = claims["sub"], claims.get("username", "Builder")
            if user_id == getattr(settings, "showcase_user_sub", ""):
                name = "Marketplace Demo"
        except (jwt.PyJWTError, ValueError):
            raise HTTPException(
                401, "Your session has expired. Please sign in again"
            ) from None
    user = db.get(User, user_id)
    if not user:
        # Concurrent first requests must not race on the primary key.
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
        db.execute(
            insert(User)
            .values(id=user_id, name=name)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        db.commit()
        user = db.get(User, user_id)
    return user
