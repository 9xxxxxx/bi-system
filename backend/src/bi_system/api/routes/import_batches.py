from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bi_system.api.dependencies import get_database_session, get_file_storage
from bi_system.core.config import Settings, get_settings
from bi_system.db.models import FileBlob, ImportBatch, ImportIssueSample, ImportTarget
from bi_system.ingestion.batch_contracts import CreateImportBatch
from bi_system.ingestion.batches import (
    ImportBatchConfigurationError,
    ImportBatchResourceNotFoundError,
    ImportBatchStateError,
    StoredImportBatch,
    cancel_import_batch,
    confirm_import_batch_warnings,
    create_import_batch,
    get_import_batch,
    list_import_batches,
    retry_import_batch,
)
from bi_system.ingestion.domain import ImportBatchStatus, ImportMode
from bi_system.ingestion.storage import LocalContentAddressedStorage

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]
FileStorage = Annotated[LocalContentAddressedStorage, Depends(get_file_storage)]


class ImportTargetSummary(BaseModel):
    id: UUID
    name: str
    physical_table_name: str


class ImportBatchResponse(BaseModel):
    id: UUID
    source_file_id: UUID
    template_id: UUID | None
    target: ImportTargetSummary
    mode: ImportMode
    status: ImportBatchStatus
    total_rows: int | None
    processed_rows: int
    valid_rows: int
    error_rows: int
    warning_rows: int
    checkpoint_row: int
    attempt_count: int
    cancellation_requested: bool
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class ImportIssueResponse(BaseModel):
    id: UUID
    row_number: int
    column_name: str | None
    severity: str
    code: str
    message: str
    raw_value: str | None


class ImportIssuePageResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ImportIssueResponse]


@router.post("", response_model=ImportBatchResponse, status_code=status.HTTP_201_CREATED)
def create_import_batch_endpoint(
    request_body: CreateImportBatch,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> ImportBatchResponse:
    try:
        stored = create_import_batch(
            session,
            workspace_id=settings.workspace_id,
            request=request_body,
        )
    except ImportBatchResourceNotFoundError as exc:
        raise _batch_http_error(
            404, "import_resource_not_found", str(exc), "Choose an available resource"
        ) from exc
    except ImportBatchConfigurationError as exc:
        raise _batch_http_error(
            422, "invalid_import_configuration", str(exc), "Correct the import mapping"
        ) from exc
    return _stored_batch_response(stored)


@router.get("", response_model=list[ImportBatchResponse])
def list_import_batches_endpoint(
    session: DatabaseSession,
    settings: ApplicationSettings,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ImportBatchResponse]:
    return [
        _stored_batch_response(stored)
        for stored in list_import_batches(
            session,
            workspace_id=settings.workspace_id,
            limit=limit,
        )
    ]


@router.get("/{batch_id}", response_model=ImportBatchResponse)
def read_import_batch_endpoint(
    batch_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> ImportBatchResponse:
    stored = get_import_batch(session, workspace_id=settings.workspace_id, batch_id=batch_id)
    if stored is None:
        raise _batch_http_error(
            404, "import_batch_not_found", "Import batch was not found", "Refresh the batch list"
        )
    return _stored_batch_response(stored)


@router.get("/{batch_id}/issues", response_model=ImportIssuePageResponse)
def list_import_batch_issues_endpoint(
    batch_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ImportIssuePageResponse:
    stored = get_import_batch(session, workspace_id=settings.workspace_id, batch_id=batch_id)
    if stored is None:
        raise _batch_http_error(
            404,
            "import_batch_not_found",
            "Import batch was not found",
            "Refresh the batch list",
        )
    total = (
        session.scalar(
            select(func.count())
            .select_from(ImportIssueSample)
            .where(ImportIssueSample.batch_id == batch_id),
        )
        or 0
    )
    issues = session.scalars(
        select(ImportIssueSample)
        .where(ImportIssueSample.batch_id == batch_id)
        .order_by(ImportIssueSample.row_number, ImportIssueSample.created_at)
        .offset(offset)
        .limit(limit),
    ).all()
    return ImportIssuePageResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=[
            ImportIssueResponse(
                id=issue.id,
                row_number=issue.row_number,
                column_name=issue.column_name,
                severity=issue.severity,
                code=issue.code,
                message=issue.message,
                raw_value=issue.raw_value,
            )
            for issue in issues
        ],
    )


@router.get("/{batch_id}/report", response_class=FileResponse)
def download_import_batch_report_endpoint(
    batch_id: UUID,
    session: DatabaseSession,
    storage: FileStorage,
    settings: ApplicationSettings,
) -> FileResponse:
    stored = get_import_batch(session, workspace_id=settings.workspace_id, batch_id=batch_id)
    if stored is None:
        raise _batch_http_error(
            404,
            "import_batch_not_found",
            "Import batch was not found",
            "Refresh the batch list",
        )
    if stored.batch.error_report_blob_id is None:
        raise _batch_http_error(
            404,
            "quality_report_not_found",
            "Quality report is not available",
            "Wait for validation to finish",
        )
    blob = session.get(FileBlob, stored.batch.error_report_blob_id)
    if blob is None:
        raise _batch_http_error(
            404,
            "quality_report_not_found",
            "Quality report file is missing",
            "Run the import again",
        )
    return FileResponse(
        storage.path_for(blob.storage_key),
        media_type=blob.media_type,
        filename=f"import-errors-{batch_id}.csv",
    )


@router.post("/{batch_id}/cancel", response_model=ImportBatchResponse)
def cancel_import_batch_endpoint(
    batch_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> ImportBatchResponse:
    try:
        cancel_import_batch(
            session,
            workspace_id=settings.workspace_id,
            batch_id=batch_id,
        )
    except ImportBatchResourceNotFoundError as exc:
        raise _batch_http_error(
            404, "import_batch_not_found", str(exc), "Refresh the batch list"
        ) from exc
    except ImportBatchStateError as exc:
        raise _batch_http_error(
            409, "invalid_batch_state", str(exc), "Refresh the batch status"
        ) from exc
    stored = get_import_batch(session, workspace_id=settings.workspace_id, batch_id=batch_id)
    if stored is None:
        raise _batch_http_error(
            404, "import_batch_not_found", "Import batch was not found", "Refresh the batch list"
        )
    return _stored_batch_response(stored)


@router.post("/{batch_id}/retry", response_model=ImportBatchResponse)
def retry_import_batch_endpoint(
    batch_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> ImportBatchResponse:
    try:
        retry_import_batch(
            session,
            workspace_id=settings.workspace_id,
            batch_id=batch_id,
        )
    except ImportBatchResourceNotFoundError as exc:
        raise _batch_http_error(
            404, "import_batch_not_found", str(exc), "Refresh the batch list"
        ) from exc
    except ImportBatchStateError as exc:
        raise _batch_http_error(
            409, "invalid_batch_state", str(exc), "Retry only failed batches"
        ) from exc
    stored = get_import_batch(session, workspace_id=settings.workspace_id, batch_id=batch_id)
    if stored is None:
        raise _batch_http_error(
            404, "import_batch_not_found", "Import batch was not found", "Refresh the batch list"
        )
    return _stored_batch_response(stored)


@router.post("/{batch_id}/confirm-warnings", response_model=ImportBatchResponse)
def confirm_import_batch_warnings_endpoint(
    batch_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> ImportBatchResponse:
    try:
        confirm_import_batch_warnings(
            session,
            workspace_id=settings.workspace_id,
            batch_id=batch_id,
        )
    except ImportBatchResourceNotFoundError as exc:
        raise _batch_http_error(
            404,
            "import_batch_not_found",
            str(exc),
            "Refresh the batch list",
        ) from exc
    except ImportBatchStateError as exc:
        raise _batch_http_error(
            409,
            "invalid_batch_state",
            str(exc),
            "Confirm warnings only when requested",
        ) from exc
    stored = get_import_batch(session, workspace_id=settings.workspace_id, batch_id=batch_id)
    if stored is None:
        raise _batch_http_error(
            404,
            "import_batch_not_found",
            "Import batch was not found",
            "Refresh the batch list",
        )
    return _stored_batch_response(stored)


def _stored_batch_response(stored: StoredImportBatch) -> ImportBatchResponse:
    return _batch_response(stored.batch, stored.target)


def _batch_response(batch: ImportBatch, target: ImportTarget) -> ImportBatchResponse:
    return ImportBatchResponse(
        id=batch.id,
        source_file_id=batch.source_file_id,
        template_id=batch.template_id,
        target=ImportTargetSummary(
            id=target.id,
            name=target.name,
            physical_table_name=target.physical_table_name,
        ),
        mode=ImportMode(batch.mode),
        status=ImportBatchStatus(batch.status),
        total_rows=batch.total_rows,
        processed_rows=batch.processed_rows,
        valid_rows=batch.valid_rows,
        error_rows=batch.error_rows,
        warning_rows=batch.warning_rows,
        checkpoint_row=batch.checkpoint_row,
        attempt_count=batch.attempt_count,
        cancellation_requested=batch.cancellation_requested,
        error_code=batch.error_code,
        error_message=batch.error_message,
        created_at=batch.created_at,
        started_at=batch.started_at,
        finished_at=batch.finished_at,
        updated_at=batch.updated_at,
    )


def _batch_http_error(status_code: int, code: str, message: str, action: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "action": action},
    )
