from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import Table, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bi_system.core.config import Settings
from bi_system.db.models import (
    FileBlob,
    ImportBatch,
    ImportIssueSample,
    ImportTarget,
    SourceFile,
)
from bi_system.ingestion.batches import claim_next_import_batch
from bi_system.ingestion.domain import (
    FileKind,
    ImportBatchStatus,
    ImportMode,
    QualitySeverity,
    validate_import_batch_transition,
)
from bi_system.ingestion.readers import iter_csv_rows, iter_xlsx_rows
from bi_system.ingestion.storage import LocalContentAddressedStorage
from bi_system.ingestion.target_tables import (
    build_target_table,
    discard_batch_rows,
    ensure_target_table,
    finalize_batch_rows,
    stage_evaluated_rows,
)
from bi_system.ingestion.template_contracts import ImportTemplateDefinition
from bi_system.ingestion.validation import EvaluatedRow, QualityEvaluator


class ImportWorkerError(RuntimeError):
    pass


class ImportWorkerLostLeaseError(ImportWorkerError):
    pass


class ImportRowLimitExceededError(ImportWorkerError):
    pass


@dataclass(frozen=True, slots=True)
class BatchWork:
    batch_id: UUID
    source_path: Path
    file_kind: FileKind
    target: ImportTarget
    definition: ImportTemplateDefinition
    encoding: str
    warnings_confirmed: bool
    checkpoint_row: int


def run_next_import_batch(
    engine: Engine,
    session_factory: sessionmaker[Session],
    storage: LocalContentAddressedStorage,
    settings: Settings,
    *,
    worker_id: str,
) -> ImportBatch | None:
    with session_factory() as session:
        claimed = claim_next_import_batch(
            session,
            worker_id=worker_id,
            lease_seconds=settings.import_worker_lease_seconds,
        )
    if claimed is None:
        return None

    try:
        process_import_batch(
            engine,
            session_factory,
            storage,
            settings,
            batch_id=claimed.id,
            worker_id=worker_id,
        )
    except ImportWorkerLostLeaseError:
        pass
    except Exception as exc:  # Worker boundary converts failures to public state.
        _mark_worker_failure(
            session_factory,
            batch_id=claimed.id,
            worker_id=worker_id,
            error_code="worker_error",
            error_message=type(exc).__name__,
        )

    with session_factory() as session:
        return session.get(ImportBatch, claimed.id)


def process_import_batch(
    engine: Engine,
    session_factory: sessionmaker[Session],
    storage: LocalContentAddressedStorage,
    settings: Settings,
    *,
    batch_id: UUID,
    worker_id: str,
) -> None:
    work = _load_batch_work(
        session_factory,
        storage,
        batch_id=batch_id,
        worker_id=worker_id,
    )
    target_table = build_target_table(work.target, work.definition)
    ensure_target_table(engine, target_table)
    evaluator = QualityEvaluator(
        work.definition,
        warnings_confirmed=work.warnings_confirmed,
    )
    rows = _source_data_rows(work)
    pending_rows: list[EvaluatedRow] = []
    processed_source_rows = 0
    with session_factory() as session:
        sample_count = (
            session.scalar(
                select(func.count())
                .select_from(ImportIssueSample)
                .where(ImportIssueSample.batch_id == batch_id),
            )
            or 0
        )

    try:
        for processed_source_rows, row_number, row in rows:
            if processed_source_rows > settings.import_max_rows:
                raise ImportRowLimitExceededError
            evaluated = evaluator.evaluate(row, row_number=row_number)
            if processed_source_rows <= work.checkpoint_row:
                continue
            pending_rows.append(evaluated)
            if len(pending_rows) >= settings.import_chunk_rows:
                committed, added_samples = _commit_chunk(
                    session_factory,
                    target_table,
                    settings,
                    batch_id=batch_id,
                    worker_id=worker_id,
                    rows=pending_rows,
                    sample_count=sample_count,
                )
                sample_count += added_samples
                pending_rows = []
                if not committed:
                    return

        if pending_rows:
            committed, _added_samples = _commit_chunk(
                session_factory,
                target_table,
                settings,
                batch_id=batch_id,
                worker_id=worker_id,
                rows=pending_rows,
                sample_count=sample_count,
            )
            if not committed:
                return

        _finalize_batch(
            session_factory,
            target_table,
            batch_id=batch_id,
            worker_id=worker_id,
            total_rows=processed_source_rows,
            definition=work.definition,
        )
    except ImportRowLimitExceededError:
        _fail_and_discard_batch(
            session_factory,
            target_table,
            batch_id=batch_id,
            worker_id=worker_id,
            error_code="row_limit_exceeded",
            error_message=f"Import exceeds the {settings.import_max_rows} row limit",
        )


def _load_batch_work(
    session_factory: sessionmaker[Session],
    storage: LocalContentAddressedStorage,
    *,
    batch_id: UUID,
    worker_id: str,
) -> BatchWork:
    with session_factory() as session:
        batch = session.get(ImportBatch, batch_id)
        if batch is None or batch.target_id is None:
            raise ImportWorkerError("Import batch metadata is incomplete")
        if batch.status != ImportBatchStatus.PROCESSING.value or batch.lease_owner != worker_id:
            raise ImportWorkerLostLeaseError
        source_file = session.get(SourceFile, batch.source_file_id)
        target = session.get(ImportTarget, batch.target_id)
        if source_file is None or target is None:
            raise ImportWorkerError("Import batch resources are missing")
        blob = session.get(FileBlob, source_file.blob_id)
        if blob is None:
            raise ImportWorkerError("Source blob is missing")
        definition = ImportTemplateDefinition.model_validate(batch.configuration["definition"])
        return BatchWork(
            batch_id=batch.id,
            source_path=storage.path_for(blob.storage_key),
            file_kind=FileKind(source_file.file_kind),
            target=target,
            definition=definition,
            encoding=str(batch.configuration.get("encoding", "utf-8-sig")),
            warnings_confirmed=bool(batch.configuration.get("warnings_confirmed", False)),
            checkpoint_row=batch.checkpoint_row,
        )


def _source_data_rows(work: BatchWork) -> Iterator[tuple[int, int, tuple[object, ...]]]:
    if work.file_kind is FileKind.CSV:
        rows: Iterator[tuple[object, ...]] = iter_csv_rows(
            work.source_path,
            encoding=work.encoding,
        )
    else:
        rows = iter_xlsx_rows(work.source_path, sheet_name=work.definition.sheet_name)

    for _index in range(work.definition.header_row):
        try:
            next(rows)
        except StopIteration:
            return
    for data_index, row in enumerate(rows, start=1):
        yield data_index, work.definition.header_row + data_index, row


def _commit_chunk(
    session_factory: sessionmaker[Session],
    target_table: Table,
    settings: Settings,
    *,
    batch_id: UUID,
    worker_id: str,
    rows: list[EvaluatedRow],
    sample_count: int,
) -> tuple[bool, int]:
    with session_factory.begin() as session:
        batch = _locked_worker_batch(session, batch_id=batch_id, worker_id=worker_id)
        if batch.cancellation_requested:
            _cancel_processing_batch(session, target_table, batch)
            return False, 0

        stage_evaluated_rows(session, target_table, batch_id=batch_id, rows=rows)
        issues = [issue for row in rows for issue in row.issues]
        remaining_capacity = max(settings.import_issue_sample_limit - sample_count, 0)
        sampled_issues = issues[:remaining_capacity]
        session.add_all(
            [
                ImportIssueSample(
                    batch_id=batch_id,
                    row_number=issue.row_number,
                    column_name=issue.column_name,
                    severity=issue.severity.value,
                    code=issue.code,
                    message=issue.message,
                    raw_value=issue.raw_value,
                )
                for issue in sampled_issues
            ],
        )

        batch.processed_rows += len(rows)
        batch.valid_rows += sum(row.accepted for row in rows)
        batch.error_rows += sum(
            any(issue.severity is QualitySeverity.ERROR for issue in row.issues) for row in rows
        )
        batch.warning_rows += sum(
            any(issue.severity is QualitySeverity.WARNING for issue in row.issues) for row in rows
        )
        batch.checkpoint_row = batch.processed_rows
        now = datetime.now(UTC)
        batch.lease_expires_at = now + timedelta(seconds=settings.import_worker_lease_seconds)
        batch.updated_at = now
        return True, len(sampled_issues)


def _finalize_batch(
    session_factory: sessionmaker[Session],
    target_table: Table,
    *,
    batch_id: UUID,
    worker_id: str,
    total_rows: int,
    definition: ImportTemplateDefinition,
) -> None:
    with session_factory.begin() as session:
        batch = _locked_worker_batch(session, batch_id=batch_id, worker_id=worker_id)
        if batch.cancellation_requested:
            _cancel_processing_batch(session, target_table, batch)
            return
        batch.total_rows = total_rows
        if total_rows == 0:
            _set_quality_failure(
                session,
                target_table,
                batch,
                code="no_data_rows",
                message="Source file does not contain data rows",
            )
            return
        warnings_confirmed = bool(batch.configuration.get("warnings_confirmed", False))
        if batch.error_rows > 0:
            _set_quality_failure(
                session,
                target_table,
                batch,
                code="quality_errors",
                message="Import contains blocking quality errors",
            )
            return
        if batch.warning_rows > 0 and not warnings_confirmed:
            _set_quality_failure(
                session,
                target_table,
                batch,
                code="warnings_confirmation_required",
                message="Import warnings require confirmation",
            )
            return

        finalize_batch_rows(
            session,
            target_table,
            batch_id=batch.id,
            mode=ImportMode(batch.mode),
            business_key=definition.business_key,
        )
        target_status = (
            ImportBatchStatus.PARTIALLY_SUCCEEDED
            if batch.warning_rows > 0
            else ImportBatchStatus.SUCCEEDED
        )
        validate_import_batch_transition(ImportBatchStatus.PROCESSING, target_status)
        batch.status = target_status.value
        finished_at = datetime.now(UTC)
        batch.finished_at = finished_at
        batch.lease_owner = None
        batch.lease_expires_at = None
        batch.updated_at = finished_at


def _fail_and_discard_batch(
    session_factory: sessionmaker[Session],
    target_table: Table,
    *,
    batch_id: UUID,
    worker_id: str,
    error_code: str,
    error_message: str,
) -> None:
    with session_factory.begin() as session:
        batch = _locked_worker_batch(session, batch_id=batch_id, worker_id=worker_id)
        _set_quality_failure(
            session,
            target_table,
            batch,
            code=error_code,
            message=error_message,
        )


def _set_quality_failure(
    session: Session,
    target_table: Table,
    batch: ImportBatch,
    *,
    code: str,
    message: str,
) -> None:
    discard_batch_rows(session, target_table, batch_id=batch.id)
    validate_import_batch_transition(
        ImportBatchStatus.PROCESSING,
        ImportBatchStatus.FAILED,
    )
    batch.status = ImportBatchStatus.FAILED.value
    batch.checkpoint_row = 0
    batch.error_code = code
    batch.error_message = message
    finished_at = datetime.now(UTC)
    batch.finished_at = finished_at
    batch.lease_owner = None
    batch.lease_expires_at = None
    batch.updated_at = finished_at


def _cancel_processing_batch(
    session: Session,
    target_table: Table,
    batch: ImportBatch,
) -> None:
    discard_batch_rows(session, target_table, batch_id=batch.id)
    session.execute(delete(ImportIssueSample).where(ImportIssueSample.batch_id == batch.id))
    validate_import_batch_transition(
        ImportBatchStatus.PROCESSING,
        ImportBatchStatus.CANCELLED,
    )
    batch.status = ImportBatchStatus.CANCELLED.value
    batch.processed_rows = 0
    batch.valid_rows = 0
    batch.error_rows = 0
    batch.warning_rows = 0
    batch.checkpoint_row = 0
    finished_at = datetime.now(UTC)
    batch.finished_at = finished_at
    batch.lease_owner = None
    batch.lease_expires_at = None
    batch.updated_at = finished_at


def _locked_worker_batch(session: Session, *, batch_id: UUID, worker_id: str) -> ImportBatch:
    query = select(ImportBatch).where(ImportBatch.id == batch_id)
    if session.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    batch = session.scalar(query)
    if batch is None or batch.status != ImportBatchStatus.PROCESSING.value:
        raise ImportWorkerLostLeaseError
    if batch.lease_owner != worker_id:
        raise ImportWorkerLostLeaseError
    return batch


def _mark_worker_failure(
    session_factory: sessionmaker[Session],
    *,
    batch_id: UUID,
    worker_id: str,
    error_code: str,
    error_message: str,
) -> None:
    with session_factory.begin() as session:
        batch = session.get(ImportBatch, batch_id)
        if batch is None or batch.lease_owner != worker_id:
            return
        if batch.status != ImportBatchStatus.PROCESSING.value:
            return
        validate_import_batch_transition(
            ImportBatchStatus.PROCESSING,
            ImportBatchStatus.FAILED,
        )
        batch.status = ImportBatchStatus.FAILED.value
        batch.error_code = error_code
        batch.error_message = error_message[:500]
        finished_at = datetime.now(UTC)
        batch.finished_at = finished_at
        batch.lease_owner = None
        batch.lease_expires_at = None
        batch.updated_at = finished_at
