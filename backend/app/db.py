import json
from functools import lru_cache

import boto3
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    settings = get_settings()
    url = settings.database_url
    if (
        settings.app_mode == "aws"
        and not settings.database_secret_arn
        and not url.startswith("postgresql")
    ):
        raise RuntimeError("AWS mode requires PostgreSQL or DATABASE_SECRET_ARN")
    if settings.database_secret_arn:
        secret = boto3.client(
            "secretsmanager", region_name=settings.aws_region
        ).get_secret_value(SecretId=settings.database_secret_arn)
        data = json.loads(secret["SecretString"])
        url = URL.create(
            "postgresql+psycopg",
            username=data["username"],
            password=data["password"],
            host=data["host"],
            port=int(data.get("port", 5432)),
            database=data.get("dbname", "marketplace"),
            query={"sslmode": "require"},
        )
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 30}
        if str(url).startswith("sqlite")
        else {},
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_settings(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    return engine


def session_factory():
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_db():
    with session_factory()() as db:
        yield db
