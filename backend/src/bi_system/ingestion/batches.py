from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from bi_system.db.models import ImportBatch, ImportColumn, ImportTarget, ImportTemplate, SourceFile
from bi_system.ingestion.batch_contracts import CreateImportBatch
from bi_system.ingestion.domain import (
    FileKind,
    ImportBatchStatus,
    ImportMode,
    validate_import_batch_transition,
)
from bi_system.ingestion.template_contracts import ImportTemplateDefinition


class ImportBatchError(ValueError):
    """Base error for import batch lifecycle operations."""


class ImportBatchResourceNotFoundError(ImportBatchError):
    pass


class ImportBatchConfigurationError(ImportBatchError):
    pass


class ImportBatchStateError(ImportBatchError):
    pass


@dataclass(frozen=True, slots=True)
class StoredImportBatch:
    batch: ImportBatch
    target: ImportTarget
    definition: ImportTemplateDefinition


def create_import_batch(
    session: Session,
    *,
    workspace_id: UUID,
    request: CreateImportBatch,
) -> StoredImportBatch:
    with session.begin():
        source_file = session.get(SourceFile, request.source_file_id)
        if source_file is None or source_file.workspace_id != workspace_id:
            raise ImportBatchResourceNotFoundError("Source file was not found")

        template, definition = _resolve_definition(
            session,
            workspace_id=workspace_id,
            request=request,
        )
        if FileKind(source_file.file_kind) is not definition.file_kind:
            raise ImportBatchConfigurationError(
                "Source file type does not match the import definition",
            )
        if request.mode is ImportMode.UPSERT and not definition.business_key:
            raise ImportBatchConfigurationError("Upsert imports require a business key")

        target = _resolve_target(
            session,
            workspace_id=workspace_id,
            request=request,
            definition=definition,
        )
        batch = ImportBatch(
            workspace_id=workspace_id,
            source_file_id=source_file.id,
            template_id=template.id if template is not None else None,
            target_id=target.id,
            mode=request.mode.value,
            status=ImportBatchStatus.PENDING.value,
            sheet_name=definition.sheet_name,
            configuration={
                "encoding": request.encoding,
                "warnings_confirmed": request.warnings_confirmed,
                "definition": definition.model_dump(mode="json"),
            },
        )
        session.add(batch)
        session.flush()

    return StoredImportBatch(batch=batch, target=target, definition=definition)


def get_import_batch(
    session: Session,
    *,
    workspace_id: UUID,
    batch_id: UUID,
) -> StoredImportBatch | None:
    batch = session.get(ImportBatch, batch_id)
    if batch is None or batch.workspace_id != workspace_id or batch.target_id is None:
        return None
    target = session.get(ImportTarget, batch.target_id)
    if target is None:
        return None
    definition = ImportTemplateDefinition.model_validate(batch.configuration["definition"])
    return StoredImportBatch(batch=batch, target=target, definition=definition)


def list_import_batches(
    session: Session,
    *,
    workspace_id: UUID,
    limit: int,
) -> list[StoredImportBatch]:
    batches = session.scalars(
        select(ImportBatch)
        .where(ImportBatch.workspace_id == workspace_id)
        .order_by(ImportBatch.created_at.desc())
        .limit(limit),
    ).all()
    stored_batches: list[StoredImportBatch] = []
    for batch in batches:
        if batch.target_id is None:
            continue
        target = session.get(ImportTarget, batch.target_id)
        if target is None:
            continue
        stored_batches.append(
            StoredImportBatch(
                batch=batch,
                target=target,
                definition=ImportTemplateDefinition.model_validate(
                    batch.configuration["definition"],
                ),
            ),
        )
    return stored_batches


def cancel_import_batch(
    session: Session,
    *,
    workspace_id: UUID,
    batch_id: UUID,
    now: datetime | None = None,
) -> ImportBatch:
    current_time = now or datetime.now(UTC)
    with session.begin():
        batch = _required_batch(session, workspace_id=workspace_id, batch_id=batch_id)
        current_status = ImportBatchStatus(batch.status)
        if current_status in {ImportBatchStatus.PENDING, ImportBatchStatus.FAILED}:
            validate_import_batch_transition(current_status, ImportBatchStatus.CANCELLED)
            batch.status = ImportBatchStatus.CANCELLED.value
            batch.finished_at = current_time
        elif current_status is ImportBatchStatus.PROCESSING:
            batch.cancellation_requested = True
        else:
            raise ImportBatchStateError(f"Cannot cancel an import batch in {batch.status} status")
        batch.updated_at = current_time
    return batch


def retry_import_batch(
    session: Session,
    *,
    workspace_id: UUID,
    batch_id: UUID,
    now: datetime | None = None,
) -> ImportBatch:
    current_time = now or datetime.now(UTC)
    with session.begin():
        batch = _required_batch(session, workspace_id=workspace_id, batch_id=batch_id)
        current_status = ImportBatchStatus(batch.status)
        if current_status is not ImportBatchStatus.FAILED:
            raise ImportBatchStateError(f"Cannot retry an import batch in {batch.status} status")
        validate_import_batch_transition(current_status, ImportBatchStatus.PENDING)
        batch.status = ImportBatchStatus.PENDING.value
        batch.available_at = current_time
        batch.lease_owner = None
        batch.lease_expires_at = None
        batch.cancellation_requested = False
        batch.error_code = None
        batch.error_message = None
        batch.finished_at = None
        batch.updated_at = current_time
    return batch


def claim_next_import_batch(
    session: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> ImportBatch | None:
    if not worker_id.strip():
        raise ValueError("worker_id must not be empty")
    if len(worker_id) > 128:
        raise ValueError("worker_id must not exceed 128 characters")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    current_time = now or datetime.now(UTC)
    claimable = or_(
        and_(
            ImportBatch.status == ImportBatchStatus.PENDING.value,
            ImportBatch.available_at <= current_time,
        ),
        and_(
            ImportBatch.status == ImportBatchStatus.PROCESSING.value,
            ImportBatch.lease_expires_at.is_not(None),
            ImportBatch.lease_expires_at <= current_time,
        ),
    )
    query = (
        select(ImportBatch)
        .where(claimable)
        .order_by(ImportBatch.available_at, ImportBatch.created_at)
    )
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)

    with session.begin():
        batch = session.scalar(query.limit(1))
        if batch is None:
            return None
        if batch.status == ImportBatchStatus.PENDING.value:
            validate_import_batch_transition(
                ImportBatchStatus.PENDING,
                ImportBatchStatus.PROCESSING,
            )
            batch.status = ImportBatchStatus.PROCESSING.value
        batch.attempt_count += 1
        batch.lease_owner = worker_id
        batch.lease_expires_at = current_time + timedelta(seconds=lease_seconds)
        batch.started_at = batch.started_at or current_time
        batch.updated_at = current_time
    return batch


def _resolve_definition(
    session: Session,
    *,
    workspace_id: UUID,
    request: CreateImportBatch,
) -> tuple[ImportTemplate | None, ImportTemplateDefinition]:
    if request.definition is not None:
        return None, request.definition
    if request.template_id is None:
        raise ImportBatchConfigurationError("Import definition is required")
    template = session.get(ImportTemplate, request.template_id)
    if template is None or template.workspace_id != workspace_id:
        raise ImportBatchResourceNotFoundError("Import template was not found")
    return template, ImportTemplateDefinition.model_validate(template.configuration)


def _resolve_target(
    session: Session,
    *,
    workspace_id: UUID,
    request: CreateImportBatch,
    definition: ImportTemplateDefinition,
) -> ImportTarget:
    if request.target_id is not None:
        target = session.get(ImportTarget, request.target_id)
        if target is None or target.workspace_id != workspace_id:
            raise ImportBatchResourceNotFoundError("Import target was not found")
        _validate_target_columns(session, target=target, definition=definition)
        return target

    if request.target_name is None:
        raise ImportBatchConfigurationError("Target name is required")
    existing_target = session.scalar(
        select(ImportTarget).where(
            ImportTarget.workspace_id == workspace_id,
            ImportTarget.name == request.target_name,
        ),
    )
    if existing_target is not None:
        raise ImportBatchConfigurationError("Target name already exists; select its target_id")

    target_id = uuid4()
    target = ImportTarget(
        id=target_id,
        workspace_id=workspace_id,
        name=request.target_name,
        physical_table_name=f"data_{target_id.hex}",
        status="active",
    )
    session.add(target)
    session.flush()
    session.add_all(
        [
            ImportColumn(
                target_id=target_id,
                source_name=column.source_name,
                physical_name=column.target_name,
                data_type=column.data_type.value,
                nullable=column.nullable,
                ordinal=index,
            )
            for index, column in enumerate(definition.columns)
        ],
    )
    session.flush()
    return target


def _validate_target_columns(
    session: Session,
    *,
    target: ImportTarget,
    definition: ImportTemplateDefinition,
) -> None:
    stored_columns = session.scalars(
        select(ImportColumn)
        .where(ImportColumn.target_id == target.id)
        .order_by(ImportColumn.ordinal),
    ).all()
    expected = [
        (column.target_name, column.data_type.value, column.nullable)
        for column in definition.columns
    ]
    actual = [
        (column.physical_name, column.data_type, column.nullable) for column in stored_columns
    ]
    if actual != expected:
        raise ImportBatchConfigurationError("Import definition does not match target columns")


def _required_batch(session: Session, *, workspace_id: UUID, batch_id: UUID) -> ImportBatch:
    batch = session.get(ImportBatch, batch_id)
    if batch is None or batch.workspace_id != workspace_id:
        raise ImportBatchResourceNotFoundError("Import batch was not found")
    return batch
