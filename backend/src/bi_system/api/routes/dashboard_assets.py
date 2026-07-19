from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bi_system.api.dependencies import (
    CurrentActor,
    get_database_session,
    get_file_storage,
)
from bi_system.dashboards.assets import (
    DashboardAssetError,
    DashboardAssetRecord,
    get_dashboard_asset_content,
    list_dashboard_assets,
    register_dashboard_asset,
)
from bi_system.ingestion.storage import LocalContentAddressedStorage

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_database_session)]
FileStorage = Annotated[LocalContentAddressedStorage, Depends(get_file_storage)]


class DashboardAssetResponse(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str
    created_at: datetime


class UploadDashboardAssetResponse(DashboardAssetResponse):
    duplicate: bool


class DashboardAssetListResponse(BaseModel):
    items: list[DashboardAssetResponse]
    total: int
    offset: int
    limit: int


@router.post(
    "",
    response_model=UploadDashboardAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_dashboard_asset_endpoint(
    file: Annotated[UploadFile, File()],
    session: DatabaseSession,
    storage: FileStorage,
    actor: CurrentActor,
) -> UploadDashboardAssetResponse:
    try:
        registered = register_dashboard_asset(
            session,
            storage,
            principal=actor,
            original_name=file.filename,
            declared_media_type=file.content_type,
            stream=file.file,
        )
    except DashboardAssetError as exc:
        raise _dashboard_asset_http_error(exc) from exc
    response = _asset_response(registered)
    return UploadDashboardAssetResponse(
        **response.model_dump(),
        duplicate=registered.duplicate,
    )


@router.get("", response_model=DashboardAssetListResponse)
def list_dashboard_assets_endpoint(
    session: DatabaseSession,
    actor: CurrentActor,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DashboardAssetListResponse:
    try:
        page = list_dashboard_assets(
            session,
            principal=actor,
            offset=offset,
            limit=limit,
        )
    except DashboardAssetError as exc:
        raise _dashboard_asset_http_error(exc) from exc
    return DashboardAssetListResponse(
        items=[_asset_response(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.get("/{asset_id}/content", response_class=FileResponse)
def read_dashboard_asset_content_endpoint(
    asset_id: UUID,
    session: DatabaseSession,
    storage: FileStorage,
    actor: CurrentActor,
) -> FileResponse:
    try:
        content = get_dashboard_asset_content(
            session,
            storage,
            principal=actor,
            asset_id=asset_id,
        )
    except DashboardAssetError as exc:
        raise _dashboard_asset_http_error(exc) from exc
    return FileResponse(
        content.path,
        media_type=content.blob.media_type,
        filename=content.asset.original_name,
        content_disposition_type="inline",
    )


def _asset_response(record: DashboardAssetRecord) -> DashboardAssetResponse:
    return DashboardAssetResponse(
        id=record.asset.id,
        filename=record.asset.original_name,
        content_type=record.blob.media_type,
        size_bytes=record.blob.size_bytes,
        width=record.asset.width,
        height=record.asset.height,
        sha256=record.blob.sha256,
        created_at=record.asset.created_at,
    )


def _dashboard_asset_http_error(exc: DashboardAssetError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc), "action": exc.action},
    )
