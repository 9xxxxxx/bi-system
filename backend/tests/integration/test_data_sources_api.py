# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.routes import data_sources
from bi_system.core.config import clear_settings_cache, get_settings
from bi_system.db.base import Base
from bi_system.db.models import FileBlob, ImportBatch, ImportColumn, ImportTarget, SourceFile
from bi_system.ingestion.target_tables import build_target_table
from bi_system.ingestion.template_contracts import ImportTemplateDefinition
from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class DataSourceApiContext:
    client: TestClient
    target_id: UUID
    batch_id: UUID
    other_workspace_target_id: UUID


@pytest.fixture
def data_source_api_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[DataSourceApiContext]:
    database_path = tmp_path / "data-sources.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    clear_settings_cache()
    application = create_app()
    application.include_router(data_sources.router, prefix="/api/v1/data-sources")

    with TestClient(application) as client:
        engine = cast(Engine, application.state.engine)
        Base.metadata.create_all(engine)
        session_factory = cast(sessionmaker[Session], application.state.session_factory)
        workspace_id = get_settings().workspace_id
        with session_factory.begin() as session:
            target = ImportTarget(
                workspace_id=workspace_id,
                name="城市销售数据",
                physical_table_name=f"data_{uuid4().hex}",
                status="active",
            )
            other_target = ImportTarget(
                workspace_id=uuid4(),
                name="其他工作区数据",
                physical_table_name=f"data_{uuid4().hex}",
                status="active",
            )
            session.add_all([target, other_target])
            session.flush()
            columns = [
                ImportColumn(
                    target_id=target.id,
                    source_name="城市",
                    physical_name="city",
                    data_type="string",
                    nullable=False,
                    ordinal=0,
                ),
                ImportColumn(
                    target_id=target.id,
                    source_name="销售额",
                    physical_name="amount",
                    data_type="decimal",
                    nullable=True,
                    ordinal=1,
                ),
            ]
            session.add_all(columns)

            blob = FileBlob(
                sha256="d" * 64,
                size_bytes=32,
                media_type="text/csv",
                storage_key="sha256/dd/dd/" + "d" * 64,
            )
            session.add(blob)
            session.flush()
            source_file = SourceFile(
                workspace_id=workspace_id,
                blob_id=blob.id,
                original_name="sales.csv",
                file_kind="csv",
                status="ready",
            )
            session.add(source_file)
            session.flush()
            batch = ImportBatch(
                workspace_id=workspace_id,
                source_file_id=source_file.id,
                target_id=target.id,
                mode="append",
                status="succeeded",
                configuration={},
                total_rows=3,
                processed_rows=3,
                valid_rows=3,
                finished_at=datetime.now(UTC),
            )
            session.add(batch)
            session.flush()
            target_id = target.id
            batch_id = batch.id
            other_target_id = other_target.id

        definition = ImportTemplateDefinition.model_validate(
            {
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
                        "source_name": "销售额",
                        "target_name": "amount",
                        "data_type": "decimal",
                        "nullable": True,
                    },
                ],
            },
        )
        table = build_target_table(target, definition)
        table.create(engine)
        with session_factory.begin() as session:
            session.execute(
                table.insert(),
                [
                    {
                        "_row_id": uuid4(),
                        "_batch_id": batch_id,
                        "_row_number": 1,
                        "_active": True,
                        "city": "北京",
                        "amount": 100,
                    },
                    {
                        "_row_id": uuid4(),
                        "_batch_id": batch_id,
                        "_row_number": 2,
                        "_active": True,
                        "city": "上海",
                        "amount": 200,
                    },
                    {
                        "_row_id": uuid4(),
                        "_batch_id": batch_id,
                        "_row_number": 3,
                        "_active": False,
                        "city": "广州",
                        "amount": 300,
                    },
                ],
            )

        yield DataSourceApiContext(
            client=client,
            target_id=target_id,
            batch_id=batch_id,
            other_workspace_target_id=other_target_id,
        )

    clear_settings_cache()


def test_lists_workspace_data_sources_without_physical_names(
    data_source_api_context: DataSourceApiContext,
) -> None:
    response = cast(Response, data_source_api_context.client.get("/api/v1/data-sources"))

    assert response.status_code == 200
    body = response.json()
    assert [{key: source[key] for key in source if key != "fields"} for source in body] == [
        {
            "id": str(data_source_api_context.target_id),
            "name": "城市销售数据",
            "status": "active",
            "latest_active_batch_id": str(data_source_api_context.batch_id),
            "active_row_count": 2,
        },
    ]
    assert [field["display_name"] for field in body[0]["fields"]] == ["城市", "销售额"]
    assert "physical_table_name" not in response.text


def test_reads_data_source_schema_with_stable_field_ids(
    data_source_api_context: DataSourceApiContext,
) -> None:
    response = cast(
        Response,
        data_source_api_context.client.get(
            f"/api/v1/data-sources/{data_source_api_context.target_id}/schema",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["active_row_count"] == 2
    assert body["latest_active_batch_id"] == str(data_source_api_context.batch_id)
    assert [
        {key: field[key] for key in ("display_name", "data_type", "nullable")}
        for field in body["fields"]
    ] == [
        {"display_name": "城市", "data_type": "string", "nullable": False},
        {"display_name": "销售额", "data_type": "decimal", "nullable": True},
    ]
    assert all(UUID(field["id"]) for field in body["fields"])
    assert "physical_table_name" not in response.text
    assert "physical_name" not in response.text


def test_data_source_schema_hides_cross_workspace_resources(
    data_source_api_context: DataSourceApiContext,
) -> None:
    response = cast(
        Response,
        data_source_api_context.client.get(
            f"/api/v1/data-sources/{data_source_api_context.other_workspace_target_id}/schema",
        ),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "data_source_not_found"
