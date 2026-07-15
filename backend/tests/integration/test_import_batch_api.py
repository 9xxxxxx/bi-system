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


def inline_definition(*, file_kind: str = "csv", business_key: bool = True) -> dict[str, Any]:
    return {
        "file_kind": file_kind,
        "columns": [
            {
                "source_key": "column_1",
                "source_name": "城市",
                "target_name": "city",
                "data_type": "string",
                "nullable": False,
            },
        ],
        "business_key": ["city"] if business_key else [],
        "quality_rules": [],
    }


@pytest.fixture
def import_batch_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    database_path = tmp_path / "batch-api.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    clear_settings_cache()
    application = create_app()

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        yield client

    clear_settings_cache()


def upload_csv(client: TestClient) -> str:
    response = cast(
        Response,
        client.post(
            "/api/v1/source-files",
            files={"file": ("cities.csv", "城市\n北京\n".encode(), "text/csv")},
        ),
    )
    assert response.status_code == 201
    return cast(str, response.json()["id"])


def test_batch_api_creates_reads_and_cancels_batch(import_batch_client: TestClient) -> None:
    source_file_id = upload_csv(import_batch_client)
    create_response = cast(
        Response,
        import_batch_client.post(
            "/api/v1/import-batches",
            json={
                "source_file_id": source_file_id,
                "definition": inline_definition(),
                "target_name": "城市数据",
                "mode": "append",
            },
        ),
    )

    assert create_response.status_code == 201, create_response.text
    body = create_response.json()
    assert body["status"] == "pending"
    assert body["target"]["physical_table_name"].startswith("data_")
    assert body["processed_rows"] == 0

    list_response = cast(Response, import_batch_client.get("/api/v1/import-batches"))
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [body["id"]]

    read_response = cast(
        Response,
        import_batch_client.get(f"/api/v1/import-batches/{body['id']}"),
    )
    assert read_response.status_code == 200
    assert read_response.json()["target"]["id"] == body["target"]["id"]

    cancel_response = cast(
        Response,
        import_batch_client.post(f"/api/v1/import-batches/{body['id']}/cancel"),
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    retry_response = cast(
        Response,
        import_batch_client.post(f"/api/v1/import-batches/{body['id']}/retry"),
    )
    assert retry_response.status_code == 409
    assert retry_response.json()["detail"]["code"] == "invalid_batch_state"


def test_batch_api_reuses_compatible_target(import_batch_client: TestClient) -> None:
    source_file_id = upload_csv(import_batch_client)
    first = cast(
        Response,
        import_batch_client.post(
            "/api/v1/import-batches",
            json={
                "source_file_id": source_file_id,
                "definition": inline_definition(),
                "target_name": "城市数据",
                "mode": "append",
            },
        ),
    )
    target_id = first.json()["target"]["id"]

    second = cast(
        Response,
        import_batch_client.post(
            "/api/v1/import-batches",
            json={
                "source_file_id": source_file_id,
                "definition": inline_definition(),
                "target_id": target_id,
                "mode": "replace",
            },
        ),
    )

    assert second.status_code == 201, second.text
    assert second.json()["target"]["id"] == target_id


def test_batch_api_rejects_source_type_mismatch(import_batch_client: TestClient) -> None:
    source_file_id = upload_csv(import_batch_client)

    response = cast(
        Response,
        import_batch_client.post(
            "/api/v1/import-batches",
            json={
                "source_file_id": source_file_id,
                "definition": inline_definition(file_kind="xlsx"),
                "target_name": "城市数据",
                "mode": "append",
            },
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_import_configuration"


def test_batch_api_requires_business_key_for_upsert(import_batch_client: TestClient) -> None:
    source_file_id = upload_csv(import_batch_client)

    response = cast(
        Response,
        import_batch_client.post(
            "/api/v1/import-batches",
            json={
                "source_file_id": source_file_id,
                "definition": inline_definition(business_key=False),
                "target_name": "城市数据",
                "mode": "upsert",
            },
        ),
    )

    assert response.status_code == 422
    assert "business key" in response.text


def test_batch_api_hides_unknown_resource(import_batch_client: TestClient) -> None:
    response = cast(
        Response,
        import_batch_client.get(f"/api/v1/import-batches/{uuid4()}"),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "import_batch_not_found"
