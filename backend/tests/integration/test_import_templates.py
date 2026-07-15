# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine


def template_payload(*, maximum: int = 1000) -> dict[str, Any]:
    return {
        "name": "城市月报",
        "definition": {
            "file_kind": "csv",
            "columns": [
                {
                    "source_key": "column_1",
                    "source_name": "城市",
                    "target_name": "city",
                    "data_type": "string",
                    "nullable": False,
                },
                {
                    "source_key": "column_2",
                    "source_name": "金额",
                    "target_name": "amount",
                    "data_type": "decimal",
                },
            ],
            "business_key": ["city"],
            "quality_rules": [
                {
                    "name": "城市必填",
                    "rule_type": "required",
                    "severity": "error",
                    "column_name": "city",
                    "parameters": {},
                },
                {
                    "name": "金额范围",
                    "rule_type": "range",
                    "severity": "warning",
                    "column_name": "amount",
                    "parameters": {"minimum": 0, "maximum": maximum},
                },
            ],
        },
    }


@pytest.fixture
def import_template_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    database_path = tmp_path / "templates.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    clear_settings_cache()
    application = create_app()

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        yield client

    clear_settings_cache()


def test_template_api_creates_versions_and_archives_previous(
    import_template_client: TestClient,
) -> None:
    first = cast(
        Response,
        import_template_client.post("/api/v1/import-templates", json=template_payload()),
    )
    second = cast(
        Response,
        import_template_client.post(
            "/api/v1/import-templates",
            json=template_payload(maximum=2000),
        ),
    )

    assert first.status_code == 201
    assert first.json()["version"] == 1
    assert second.status_code == 201
    assert second.json()["version"] == 2
    assert second.json()["definition"]["quality_rules"][1]["parameters"]["maximum"] == 2000

    active = cast(Response, import_template_client.get("/api/v1/import-templates"))
    assert active.status_code == 200
    assert [(item["version"], item["status"]) for item in active.json()] == [(2, "active")]

    all_versions = cast(
        Response,
        import_template_client.get("/api/v1/import-templates?include_archived=true"),
    )
    assert [(item["version"], item["status"]) for item in all_versions.json()] == [
        (2, "active"),
        (1, "archived"),
    ]

    stored = cast(
        Response,
        import_template_client.get(f"/api/v1/import-templates/{first.json()['id']}"),
    )
    assert stored.status_code == 200
    assert stored.json()["definition"]["business_key"] == ["city"]


def test_template_api_rejects_arbitrary_rule_configuration(
    import_template_client: TestClient,
) -> None:
    payload = template_payload()
    payload["definition"]["quality_rules"][0]["parameters"] = {
        "python": "exec('unsafe')",
    }

    response = cast(
        Response,
        import_template_client.post("/api/v1/import-templates", json=payload),
    )

    assert response.status_code == 422
    assert "Extra inputs are not permitted" in response.text


def test_template_api_hides_unknown_resource(import_template_client: TestClient) -> None:
    response = cast(
        Response,
        import_template_client.get(f"/api/v1/import-templates/{uuid4()}"),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "import_template_not_found"
