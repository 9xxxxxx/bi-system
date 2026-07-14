# pyright: reportUnknownMemberType=false
from typing import cast

from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response


def test_live_endpoint_returns_service_status() -> None:
    client = TestClient(create_app())

    response = cast(Response, client.get("/api/v1/health/live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "bi-system"}
