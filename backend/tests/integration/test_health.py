# pyright: reportUnknownMemberType=false
from typing import cast

from bi_system.core.config import get_settings
from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response
from pytest import MonkeyPatch
from sqlalchemy.exc import OperationalError


def test_live_endpoint_returns_service_status() -> None:
    client = TestClient(create_app())

    response = cast(Response, client.get("/api/v1/health/live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "bi-system"}


def test_ready_endpoint_returns_database_status(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("BI_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = cast(Response, client.get("/api/v1/health/ready"))

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


class FailingEngine:
    def connect(self) -> None:
        raise OperationalError(
            "postgresql+psycopg://user:secret@localhost/db",
            None,
            RuntimeError("connection failed"),
        )


def test_ready_endpoint_hides_database_error_details(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("BI_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    get_settings.cache_clear()

    application = create_app()

    with TestClient(application) as client:
        application.state.engine = FailingEngine()
        response = cast(Response, client.get("/api/v1/health/ready"))

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "secret" not in response.text
