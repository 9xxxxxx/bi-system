from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bi_system.api.dependencies import get_database_session
from bi_system.core.config import Settings, get_settings
from bi_system.db.models import ImportBatch, ImportTarget
from bi_system.ingestion.batch_contracts import CreateImportBatch
from bi_system.ingestion.batches import (
    ImportBatchConfigurationError,
    ImportBatchResourceNotFoundError,
    ImportBatchStateError,
    StoredImportBatch,
    cancel_import_batch,
    create_import_batch,
    get_import_batch,
    list_import_batches,
    retry_import_batch,
)
from bi_system.ingestion.domain import ImportBatchStatus, ImportMode

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


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
