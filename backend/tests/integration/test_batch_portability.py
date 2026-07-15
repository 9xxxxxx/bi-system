import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from bi_system.core.config import Settings
from bi_system.db.models import FileBlob, SourceFile
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion.batch_contracts import CreateImportBatch
from bi_system.ingestion.batches import claim_next_import_batch, create_import_batch
from bi_system.ingestion.domain import ImportMode
from bi_system.ingestion.files import register_source_file
from bi_system.ingestion.storage import LocalContentAddressedStorage
from bi_system.ingestion.target_tables import build_target_table, read_active_rows
from bi_system.ingestion.template_contracts import ImportTemplateDefinition
from bi_system.ingestion.worker import run_next_import_batch


def test_batch_claim_runs_on_configured_database() -> None:
    database_url = os.environ.get("BI_DATABASE_URL")
    if database_url is None:
        pytest.skip("BI_DATABASE_URL is required for database portability checks")

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    digest = uuid4().hex * 2

    try:
        with session_factory() as session:
            with session.begin():
                blob = FileBlob(
                    sha256=digest,
                    size_bytes=64,
                    media_type="text/csv",
                    storage_key=f"sha256/{digest[:2]}/{digest[2:4]}/{digest}",
                )
                session.add(blob)
                session.flush()
                source_file = SourceFile(
                    workspace_id=workspace_id,
                    blob_id=blob.id,
                    original_name="portability.csv",
                    file_kind="csv",
                    status="ready",
                )
                session.add(source_file)
                session.flush()
                source_file_id = source_file.id

            request = CreateImportBatch.model_validate(
                {
                    "source_file_id": str(source_file_id),
                    "definition": {
                        "file_kind": "csv",
                        "columns": [
                            {
                                "source_key": "column_1",
                                "source_name": "城市",
                                "target_name": "city",
                                "data_type": "string",
                            },
                        ],
                    },
                    "target_name": f"portability-{workspace_id}",
                    "mode": "append",
                },
            )
            stored = create_import_batch(
                session,
                workspace_id=workspace_id,
                request=request,
            )
            claimed = claim_next_import_batch(
                session,
                worker_id="portability-worker",
                lease_seconds=30,
                now=datetime.now(UTC) + timedelta(seconds=1),
            )

            assert claimed is not None
            assert claimed.id == stored.batch.id
            assert claimed.status == "processing"
            assert claimed.attempt_count == 1
    finally:
        engine.dispose()


def test_worker_writes_dynamic_target_on_configured_database(tmp_path: Path) -> None:
    database_url = os.environ.get("BI_DATABASE_URL")
    if database_url is None:
        pytest.skip("BI_DATABASE_URL is required for worker portability checks")

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    storage = LocalContentAddressedStorage(tmp_path / "uploads", max_bytes=100_000)
    settings = Settings(
        database_url=database_url,
        storage_root=tmp_path / "uploads",
        upload_max_bytes=100_000,
        xlsx_max_uncompressed_bytes=1_000_000,
        import_chunk_rows=2,
        preview_max_rows=2,
    )
    workspace_id = uuid4()
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
                    "source_name": "金额",
                    "target_name": "amount",
                    "data_type": "decimal",
                },
            ],
            "business_key": ["city"],
        },
    )

    try:
        with session_factory() as session:
            source = register_source_file(
                session,
                storage,
                workspace_id=workspace_id,
                original_name="worker-portability.csv",
                stream=BytesIO("城市,金额\n北京,10\n上海,20\n".encode("utf-8-sig")),
                xlsx_max_uncompressed_bytes=settings.xlsx_max_uncompressed_bytes,
                xlsx_max_compression_ratio=settings.xlsx_max_compression_ratio,
            )
            stored = create_import_batch(
                session,
                workspace_id=workspace_id,
                request=CreateImportBatch(
                    source_file_id=source.source_file.id,
                    definition=definition,
                    target_name=f"worker-portability-{workspace_id}",
                    mode=ImportMode.APPEND,
                ),
            )
            target = stored.target

        result = run_next_import_batch(
            engine,
            session_factory,
            storage,
            settings,
            worker_id="database-portability-worker",
        )
        assert result is not None
        assert result.status == "succeeded"

        with session_factory() as session:
            rows = read_active_rows(session, build_target_table(target, definition))
            assert {row["city"]: row["amount"] for row in rows} == {
                "北京": 10,
                "上海": 20,
            }
    finally:
        engine.dispose()
