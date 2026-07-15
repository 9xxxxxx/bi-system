import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from bi_system.db.models import FileBlob, SourceFile
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion.batch_contracts import CreateImportBatch
from bi_system.ingestion.batches import claim_next_import_batch, create_import_batch


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
