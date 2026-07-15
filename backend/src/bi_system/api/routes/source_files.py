from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from bi_system.api.dependencies import get_database_session, get_file_storage
from bi_system.core.config import Settings, get_settings
from bi_system.db.models import FileBlob, SourceFile
from bi_system.ingestion.domain import FileKind
from bi_system.ingestion.files import (
    InvalidSourceContentError,
    InvalidSourceFilenameError,
    RegisteredSourceFile,
    UnsupportedSourceFileError,
    get_source_file,
    register_source_file,
)
from bi_system.ingestion.preview import JsonCell, SourcePreviewError, preview_source_file
from bi_system.ingestion.readers import IngestionReaderError
from bi_system.ingestion.storage import (
    EmptyUploadError,
    LocalContentAddressedStorage,
    StoredBlobIntegrityError,
    UploadTooLargeError,
)

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
FileStorage = Annotated[LocalContentAddressedStorage, Depends(get_file_storage)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class SourceFileResponse(BaseModel):
    id: UUID
    original_name: str
    file_kind: FileKind
    status: str
    size_bytes: int
    sha256: str
    media_type: str
    created_at: datetime


class UploadSourceFileResponse(SourceFileResponse):
    duplicate: bool


class PreviewSourceFileRequest(BaseModel):
    encoding: Literal["utf-8", "utf-8-sig", "gb18030"] = "utf-8-sig"
    sheet_name: str | None = Field(default=None, max_length=128)


class PreviewColumnResponse(BaseModel):
    key: str
    source_name: str
    inferred_type: str
    null_count: int


class PreviewSourceFileResponse(BaseModel):
    source_file_id: UUID
    file_kind: FileKind
    sheet_names: list[str]
    selected_sheet: str | None
    columns: list[PreviewColumnResponse]
    rows: list[dict[str, JsonCell]]
    truncated: bool


@router.post(
    "",
    response_model=UploadSourceFileResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_source_file(
    file: Annotated[UploadFile, File()],
    session: DatabaseSession,
    storage: FileStorage,
    settings: ApplicationSettings,
) -> UploadSourceFileResponse:
    try:
        registered = register_source_file(
            session,
            storage,
            workspace_id=settings.workspace_id,
            original_name=file.filename,
            stream=file.file,
            xlsx_max_uncompressed_bytes=settings.xlsx_max_uncompressed_bytes,
            xlsx_max_compression_ratio=settings.xlsx_max_compression_ratio,
        )
    except InvalidSourceFilenameError as exc:
        raise _http_error(400, "invalid_filename", str(exc), "Rename the file and retry") from exc
    except UnsupportedSourceFileError as exc:
        raise _http_error(415, "unsupported_file_type", str(exc), "Upload CSV or XLSX") from exc
    except InvalidSourceContentError as exc:
        raise _http_error(
            422, "invalid_file_content", str(exc), "Repair or convert the file"
        ) from exc
    except EmptyUploadError as exc:
        raise _http_error(400, "empty_upload", str(exc), "Choose a non-empty file") from exc
    except UploadTooLargeError as exc:
        raise _http_error(413, "upload_too_large", str(exc), "Split the file and retry") from exc
    except StoredBlobIntegrityError as exc:
        raise _http_error(
            500,
            "stored_blob_integrity_error",
            "Stored file integrity check failed",
            "Contact the system administrator",
        ) from exc

    return _upload_response(registered)


@router.get("/{source_file_id}", response_model=SourceFileResponse)
def read_source_file(
    source_file_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> SourceFileResponse:
    record = get_source_file(
        session,
        workspace_id=settings.workspace_id,
        source_file_id=source_file_id,
    )
    if record is None:
        raise _http_error(
            404, "source_file_not_found", "Source file was not found", "Upload it again"
        )
    return _source_file_response(*record)


@router.post("/{source_file_id}/preview", response_model=PreviewSourceFileResponse)
def preview_source_file_endpoint(
    source_file_id: UUID,
    request_body: PreviewSourceFileRequest,
    session: DatabaseSession,
    storage: FileStorage,
    settings: ApplicationSettings,
) -> PreviewSourceFileResponse:
    record = get_source_file(
        session,
        workspace_id=settings.workspace_id,
        source_file_id=source_file_id,
    )
    if record is None:
        raise _http_error(
            404, "source_file_not_found", "Source file was not found", "Upload it again"
        )
    source_file, blob = record

    try:
        preview = preview_source_file(
            storage.path_for(blob.storage_key),
            file_kind=FileKind(source_file.file_kind),
            max_rows=settings.preview_max_rows,
            encoding=request_body.encoding,
            sheet_name=request_body.sheet_name,
        )
    except (IngestionReaderError, SourcePreviewError) as exc:
        raise _http_error(
            422, "preview_failed", str(exc), "Adjust the file options and retry"
        ) from exc

    return PreviewSourceFileResponse(
        source_file_id=source_file.id,
        file_kind=FileKind(source_file.file_kind),
        sheet_names=list(preview.sheet_names),
        selected_sheet=preview.selected_sheet,
        columns=[
            PreviewColumnResponse(
                key=column.key,
                source_name=column.source_name,
                inferred_type=column.inferred_type,
                null_count=column.null_count,
            )
            for column in preview.columns
        ],
        rows=list(preview.rows),
        truncated=preview.truncated,
    )


def _source_file_response(source_file: SourceFile, blob: FileBlob) -> SourceFileResponse:
    return SourceFileResponse(
        id=source_file.id,
        original_name=source_file.original_name,
        file_kind=FileKind(source_file.file_kind),
        status=source_file.status,
        size_bytes=blob.size_bytes,
        sha256=blob.sha256,
        media_type=blob.media_type,
        created_at=source_file.created_at,
    )


def _upload_response(registered: RegisteredSourceFile) -> UploadSourceFileResponse:
    response = _source_file_response(registered.source_file, registered.blob)
    return UploadSourceFileResponse(**response.model_dump(), duplicate=registered.duplicate)


def _http_error(status_code: int, code: str, message: str, action: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "action": action},
    )
