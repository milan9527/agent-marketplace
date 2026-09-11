import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import Base, get_engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    if not url.startswith("sqlite") and not url.endswith("/marketplace_test"):
        raise RuntimeError(
            "PostgreSQL tests require a dedicated marketplace_test database"
        )
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_SECRET_ARN", "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    Base.metadata.drop_all(get_engine())
    with TestClient(app) as http:
        yield http
    app.dependency_overrides.clear()
    Base.metadata.drop_all(get_engine())
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()
