from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID

from PIL import Image, ImageSequence, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bi_system.db.models.dashboards import DashboardAsset
from bi_system.db.models.ingestion import FileBlob
from bi_system.identity import QueryPrincipal
from bi_system.ingestion.storage import (
    EmptyUploadError,
    LocalContentAddressedStorage,
    StorageBoundaryError,
    StoredBlobIntegrityError,
    UploadTooLargeError,
)

MAX_DASHBOARD_ASSET_BYTES = 10 * 1024 * 1024
MAX_DASHBOARD_ASSET_PIXELS = 40_000_000
_READ_CHUNK_BYTES = 1024 * 1024
_FORMAT_MEDIA_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


class DashboardAssetError(ValueError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        action: str,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.action = action


@dataclass(frozen=True, slots=True)
class DashboardAssetRecord:
    asset: DashboardAsset
    blob: FileBlob


@dataclass(frozen=True, slots=True)
class RegisteredDashboardAsset(DashboardAssetRecord):
    duplicate: bool


@dataclass(frozen=True, slots=True)
class DashboardAssetPage:
    items: tuple[DashboardAssetRecord, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class DashboardAssetContent(DashboardAssetRecord):
    path: Path


def register_dashboard_asset(
    session: Session,
    storage: LocalContentAddressedStorage,
    *,
    principal: QueryPrincipal,
    original_name: str | None,
    declared_media_type: str | None,
    stream: BinaryIO,
) -> RegisteredDashboardAsset:
    _require_permission(principal, "dashboards:edit")
    safe_name = _normalize_filename(original_name)
    upload = _read_bounded_upload(stream)
    media_type, width, height = _inspect_image(upload)
    normalized_declared_type = (declared_media_type or "").split(";", 1)[0].strip().lower()
    if normalized_declared_type != media_type:
        raise DashboardAssetError(
            415,
            "dashboard_asset_media_type_mismatch",
            "Uploaded image content does not match its declared media type",
            "Upload the original PNG, JPEG, WebP, or GIF image",
        )

    upload.seek(0)
    try:
        stored = storage.store(upload, max_bytes=MAX_DASHBOARD_ASSET_BYTES)
    except (EmptyUploadError, UploadTooLargeError) as exc:
        raise _storage_upload_error(exc) from exc
    except StoredBlobIntegrityError as exc:
        raise DashboardAssetError(
            500,
            "dashboard_asset_storage_integrity_error",
            "Stored image integrity check failed",
            "Contact the system administrator",
        ) from exc

    with session.begin():
        blob = session.scalar(select(FileBlob).where(FileBlob.sha256 == stored.sha256))
        if blob is None:
            blob = FileBlob(
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type=media_type,
                storage_key=stored.storage_key,
            )
            session.add(blob)
            session.flush()
        elif (
            blob.size_bytes != stored.size_bytes
            or blob.storage_key != stored.storage_key
            or blob.media_type != media_type
        ):
            raise DashboardAssetError(
                500,
                "dashboard_asset_blob_metadata_conflict",
                "Stored image metadata conflicts with its content address",
                "Contact the system administrator",
            )

        asset = session.scalar(
            select(DashboardAsset).where(
                DashboardAsset.workspace_id == principal.workspace_id,
                DashboardAsset.blob_id == blob.id,
            )
        )
        duplicate = asset is not None
        if asset is None:
            asset = DashboardAsset(
                workspace_id=principal.workspace_id,
                blob_id=blob.id,
                uploaded_by_user_id=principal.user_id,
                original_name=safe_name,
                width=width,
                height=height,
            )
            session.add(asset)
            session.flush()

    return RegisteredDashboardAsset(asset=asset, blob=blob, duplicate=duplicate)


def list_dashboard_assets(
    session: Session,
    *,
    principal: QueryPrincipal,
    offset: int,
    limit: int,
) -> DashboardAssetPage:
    _require_permission(principal, "dashboards:view")
    total = session.scalar(
        select(func.count(DashboardAsset.id)).where(
            DashboardAsset.workspace_id == principal.workspace_id
        )
    )
    assets = tuple(
        session.scalars(
            select(DashboardAsset)
            .where(DashboardAsset.workspace_id == principal.workspace_id)
            .order_by(DashboardAsset.created_at.desc(), DashboardAsset.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    blobs = _blobs_by_id(session, {asset.blob_id for asset in assets})
    if len(blobs) != len({asset.blob_id for asset in assets}):
        raise DashboardAssetError(
            500,
            "dashboard_asset_blob_missing",
            "One or more dashboard image files are missing",
            "Contact the system administrator",
        )
    return DashboardAssetPage(
        items=tuple(
            DashboardAssetRecord(asset=asset, blob=blobs[asset.blob_id]) for asset in assets
        ),
        total=int(total or 0),
        offset=offset,
        limit=limit,
    )


def get_dashboard_asset_content(
    session: Session,
    storage: LocalContentAddressedStorage,
    *,
    principal: QueryPrincipal,
    asset_id: UUID,
) -> DashboardAssetContent:
    _require_permission(principal, "dashboards:view")
    asset = session.get(DashboardAsset, asset_id)
    if asset is None or asset.workspace_id != principal.workspace_id:
        raise DashboardAssetError(
            404,
            "dashboard_asset_not_found",
            "Dashboard image asset was not found",
            "Refresh the asset list",
        )
    blob = session.get(FileBlob, asset.blob_id)
    if blob is None:
        raise DashboardAssetError(
            404,
            "dashboard_asset_content_not_found",
            "Dashboard image content was not found",
            "Upload the image again",
        )
    try:
        path = storage.path_for(blob.storage_key)
    except StorageBoundaryError as exc:
        raise DashboardAssetError(
            500,
            "dashboard_asset_storage_boundary_error",
            "Dashboard image storage path is invalid",
            "Contact the system administrator",
        ) from exc
    if (
        not path.is_file()
        or path.stat().st_size != blob.size_bytes
        or _file_sha256(path) != blob.sha256
    ):
        raise DashboardAssetError(
            500,
            "dashboard_asset_storage_integrity_error",
            "Dashboard image content failed its integrity check",
            "Contact the system administrator",
        )
    return DashboardAssetContent(asset=asset, blob=blob, path=path)


def _require_permission(principal: QueryPrincipal, permission: str) -> None:
    if not principal.has_permission(permission):
        raise DashboardAssetError(
            403,
            "dashboard_asset_forbidden",
            f"{permission} permission is required",
            "Ask a workspace administrator for dashboard access",
        )


def _normalize_filename(value: str | None) -> str:
    if value is None:
        raise DashboardAssetError(
            400,
            "dashboard_asset_filename_invalid",
            "An image filename is required",
            "Choose a named image file and retry",
        )
    safe_name = PurePosixPath(value.replace("\\", "/")).name.strip()
    if not safe_name or safe_name in {".", ".."} or len(safe_name) > 255:
        raise DashboardAssetError(
            400,
            "dashboard_asset_filename_invalid",
            "Image filename is invalid or exceeds 255 characters",
            "Rename the image and retry",
        )
    return safe_name


def _read_bounded_upload(stream: BinaryIO) -> BytesIO:
    buffer = BytesIO()
    size_bytes = 0
    while chunk := stream.read(_READ_CHUNK_BYTES):
        size_bytes += len(chunk)
        if size_bytes > MAX_DASHBOARD_ASSET_BYTES:
            raise DashboardAssetError(
                413,
                "dashboard_asset_too_large",
                "Dashboard images may not exceed 10 MB",
                "Compress or resize the image and retry",
            )
        buffer.write(chunk)
    if size_bytes == 0:
        raise DashboardAssetError(
            400,
            "dashboard_asset_empty",
            "Dashboard image upload is empty",
            "Choose a non-empty image and retry",
        )
    buffer.seek(0)
    return buffer


def _inspect_image(stream: BytesIO) -> tuple[str, int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream) as image:
                image_format = image.format
                width, height = image.size
                frame_count = int(getattr(image, "n_frames", 1))
                if image_format not in _FORMAT_MEDIA_TYPES:
                    raise DashboardAssetError(
                        415,
                        "dashboard_asset_format_unsupported",
                        "Only PNG, JPEG, WebP, and GIF images are supported",
                        "Convert the image to a supported format and retry",
                    )
                if (
                    width <= 0
                    or height <= 0
                    or frame_count <= 0
                    or width * height * frame_count > MAX_DASHBOARD_ASSET_PIXELS
                ):
                    raise DashboardAssetError(
                        422,
                        "dashboard_asset_dimensions_exceeded",
                        "Dashboard image frames exceed the 40 million decoded pixel limit",
                        "Resize the image and retry",
                    )
                image.verify()
            stream.seek(0)
            with Image.open(stream) as decoded:
                for frame in ImageSequence.Iterator(decoded):
                    frame.load()
    except DashboardAssetError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DashboardAssetError(
            422,
            "dashboard_asset_dimensions_exceeded",
            "Dashboard image dimensions exceed the safe decoding limit",
            "Resize the image and retry",
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise DashboardAssetError(
            422,
            "dashboard_asset_content_invalid",
            "Dashboard image content is damaged or cannot be decoded",
            "Repair or export the image again",
        ) from exc
    finally:
        stream.seek(0)
    return _FORMAT_MEDIA_TYPES[image_format], width, height


def _storage_upload_error(exc: EmptyUploadError | UploadTooLargeError) -> DashboardAssetError:
    if isinstance(exc, EmptyUploadError):
        return DashboardAssetError(
            400,
            "dashboard_asset_empty",
            "Dashboard image upload is empty",
            "Choose a non-empty image and retry",
        )
    return DashboardAssetError(
        413,
        "dashboard_asset_too_large",
        "Dashboard images may not exceed 10 MB",
        "Compress or resize the image and retry",
    )


def _blobs_by_id(session: Session, blob_ids: set[UUID]) -> dict[UUID, FileBlob]:
    if not blob_ids:
        return {}
    return {
        blob.id: blob
        for blob in session.scalars(select(FileBlob).where(FileBlob.id.in_(blob_ids))).all()
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        while chunk := file_handle.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
