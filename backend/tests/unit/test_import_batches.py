from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bi_system.db.base import Base
from bi_system.db.models import FileBlob, ImportBatch, SourceFile
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion.batch_contracts import CreateImportBatch
from bi_system.ingestion.batches import (
    ImportBatchStateError,
    cancel_import_batch,
    claim_next_import_batch,
    create_import_batch,
    retry_import_batch,
)
from sqlalchemy.orm import Session, sessionmaker


def inline_batch_request(source_file_id: UUID) -> CreateImportBatch:
    return CreateImportBatch.model_validate(
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
                        "nullable": False,
                    },
                ],
                "business_key": ["city"],
                "quality_rules": [],
            },
            "target_name": "城市数据",
            "mode": "append",
        },
    )


@pytest.fixture
def batch_session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'batches.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    yield session_factory
    engine.dispose()


def create_source_file(session: Session, workspace_id: UUID) -> SourceFile:
    blob = FileBlob(
        sha256="c" * 64,
        size_bytes=128,
        media_type="text/csv",
        storage_key="sha256/cc/cc/" + "c" * 64,
    )
    session.add(blob)
    session.flush()
    source_file = SourceFile(
        workspace_id=workspace_id,
        blob_id=blob.id,
        original_name="cities.csv",
        file_kind="csv",
        status="ready",
    )
    session.add(source_file)
    session.flush()
    return source_file


def test_worker_claim_uses_lease_and_recovers_expired_batch(
    batch_session_factory: sessionmaker[Session],
) -> None:
    workspace_id = uuid4()
    with batch_session_factory() as session:
        with session.begin():
            source_file = create_source_file(session, workspace_id)
            source_file_id = source_file.id
        stored = create_import_batch(
            session,
            workspace_id=workspace_id,
            request=inline_batch_request(source_file_id),
        )
        batch_id = stored.batch.id

    claim_time = datetime.now(UTC) + timedelta(seconds=1)
    with batch_session_factory() as session:
        claimed = claim_next_import_batch(
            session,
            worker_id="worker-1",
            lease_seconds=30,
            now=claim_time,
        )
        assert claimed is not None
        assert claimed.id == batch_id
        assert claimed.status == "processing"
        assert claimed.attempt_count == 1

    with batch_session_factory() as session:
        assert (
            claim_next_import_batch(
                session,
                worker_id="worker-2",
                lease_seconds=30,
                now=claim_time + timedelta(seconds=10),
            )
            is None
        )

    with batch_session_factory() as session:
        recovered = claim_next_import_batch(
            session,
            worker_id="worker-2",
            lease_seconds=30,
            now=claim_time + timedelta(seconds=31),
        )
        assert recovered is not None
        assert recovered.id == batch_id
        assert recovered.lease_owner == "worker-2"
        assert recovered.attempt_count == 2


def test_cancel_pending_batch_and_reject_retry(
    batch_session_factory: sessionmaker[Session],
) -> None:
    workspace_id = uuid4()
    with batch_session_factory() as session:
        with session.begin():
            source_file = create_source_file(session, workspace_id)
            source_file_id = source_file.id
        stored = create_import_batch(
            session,
            workspace_id=workspace_id,
            request=inline_batch_request(source_file_id),
        )
        cancelled = cancel_import_batch(
            session,
            workspace_id=workspace_id,
            batch_id=stored.batch.id,
        )
        assert cancelled.status == "cancelled"

        with pytest.raises(ImportBatchStateError, match="Cannot retry"):
            retry_import_batch(
                session,
                workspace_id=workspace_id,
                batch_id=stored.batch.id,
            )


def test_retry_failed_batch_preserves_checkpoint(
    batch_session_factory: sessionmaker[Session],
) -> None:
    workspace_id = uuid4()
    with batch_session_factory() as session:
        with session.begin():
            source_file = create_source_file(session, workspace_id)
            source_file_id = source_file.id
        stored = create_import_batch(
            session,
            workspace_id=workspace_id,
            request=inline_batch_request(source_file_id),
        )
        with session.begin():
            batch = session.get(ImportBatch, stored.batch.id)
            assert batch is not None
            batch.status = "failed"
            batch.checkpoint_row = 2000
            batch.error_code = "worker_stopped"
            batch.error_message = "Worker stopped"

        retried = retry_import_batch(
            session,
            workspace_id=workspace_id,
            batch_id=stored.batch.id,
        )
        assert retried.status == "pending"
        assert retried.checkpoint_row == 2000
        assert retried.error_code is None
