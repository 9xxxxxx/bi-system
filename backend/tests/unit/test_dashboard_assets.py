# pyright: reportAny=false, reportUnknownMemberType=false
from __future__ import annotations

import struct
import zlib
from collections.abc import Generator, Iterator
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import (
    get_database_session,
    get_file_storage,
    get_query_principal,
)
from bi_system.api.routes.dashboard_assets import router
from bi_system.dashboards.assets import (
    MAX_DASHBOARD_ASSET_BYTES,
    DashboardAssetError,
    get_dashboard_asset_content,
    list_dashboard_assets,
    register_dashboard_asset,
)
from bi_system.db.base import Base
from bi_system.db.models.dashboards import DashboardAsset
from bi_system.db.models.identity import User
from bi_system.db.models.ingestion import FileBlob
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from bi_system.ingestion.storage import LocalContentAddressedStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class UnreadableStream(BytesIO):
    def read(self, _size: int | None = -1) -> bytes:
        raise AssertionError("permission denial must happen before upload reads")


@pytest.fixture
def asset_store(
    tmp_path: Path,
) -> Iterator[
    tuple[
        sessionmaker[Session],
        LocalContentAddressedStorage,
        dict[str, UUID],
        Engine,
    ]
]:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'assets.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    foreign_workspace_id = uuid4()
    with session_factory.begin() as session:
        owner = User(
            workspace_id=workspace_id,
            username="asset.owner",
            display_name="Asset Owner",
            password_hash="hash",
            must_change_password=False,
        )
        foreign = User(
            workspace_id=foreign_workspace_id,
            username="asset.foreign",
            display_name="Asset Foreign",
            password_hash="hash",
            must_change_password=False,
        )
        session.add_all([owner, foreign])
        session.flush()
        ids = {
            "workspace": workspace_id,
            "owner": owner.id,
            "foreign_workspace": foreign_workspace_id,
            "foreign": foreign.id,
        }
    storage = LocalContentAddressedStorage(tmp_path / "uploads", max_bytes=20 * 1024 * 1024)
    try:
        yield session_factory, storage, ids, engine
    finally:
        engine.dispose()


def _principal(
    *,
    workspace_id: UUID,
    user_id: UUID,
    permissions: frozenset[str] = frozenset({"dashboards:view", "dashboards:edit"}),
) -> QueryPrincipal:
    return QueryPrincipal(
        workspace_id=workspace_id,
        user_id=user_id,
        permissions=permissions,
    )


def _image_bytes(image_format: str, *, size: tuple[int, int] = (3, 2)) -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", size, color=(21, 96, 189))
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def _animated_gif_bytes(*, size: tuple[int, int], frame_count: int) -> bytes:
    buffer = BytesIO()
    frames = [Image.new("P", size, color=index % 256) for index in range(frame_count)]
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=20,
        loop=0,
    )
    for frame in frames:
        frame.close()
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("image_format", "media_type"),
    [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("WEBP", "image/webp"),
        ("GIF", "image/gif"),
    ],
)
def test_register_accepts_decoded_image_formats_and_reuses_duplicate_blob(
    asset_store: tuple[
        sessionmaker[Session], LocalContentAddressedStorage, dict[str, UUID], Engine
    ],
    image_format: str,
    media_type: str,
) -> None:
    session_factory, storage, ids, _engine = asset_store
    principal = _principal(workspace_id=ids["workspace"], user_id=ids["owner"])
    content = _image_bytes(image_format)
    with session_factory() as session:
        first = register_dashboard_asset(
            session,
            storage,
            principal=principal,
            original_name=f"image.{image_format.lower()}",
            declared_media_type=media_type,
            stream=BytesIO(content),
        )
        second = register_dashboard_asset(
            session,
            storage,
            principal=principal,
            original_name="renamed.image",
            declared_media_type=media_type,
            stream=BytesIO(content),
        )

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.asset.id == first.asset.id
    assert first.asset.width == 3
    assert first.asset.height == 2
    assert first.blob.media_type == media_type
    with session_factory() as session:
        assert session.scalar(select(func.count(DashboardAsset.id))) == 1
        assert session.scalar(select(func.count(FileBlob.id))) == 1


def test_permissions_workspace_isolation_listing_and_content_integrity(
    asset_store: tuple[
        sessionmaker[Session], LocalContentAddressedStorage, dict[str, UUID], Engine
    ],
) -> None:
    session_factory, storage, ids, _engine = asset_store
    owner = _principal(workspace_id=ids["workspace"], user_id=ids["owner"])
    viewer = _principal(
        workspace_id=ids["workspace"],
        user_id=ids["owner"],
        permissions=frozenset({"dashboards:view"}),
    )
    foreign = _principal(
        workspace_id=ids["foreign_workspace"],
        user_id=ids["foreign"],
        permissions=frozenset({"dashboards:view"}),
    )
    with session_factory() as session:
        registered = register_dashboard_asset(
            session,
            storage,
            principal=owner,
            original_name="safe.png",
            declared_media_type="image/png",
            stream=BytesIO(_image_bytes("PNG")),
        )
    with session_factory() as session:
        page = list_dashboard_assets(session, principal=viewer, offset=0, limit=10)
        content = get_dashboard_asset_content(
            session,
            storage,
            principal=viewer,
            asset_id=registered.asset.id,
        )
        assert page.total == 1
        assert page.items[0].asset.id == registered.asset.id
        assert content.path.read_bytes() == _image_bytes("PNG")
        with pytest.raises(DashboardAssetError) as hidden:
            get_dashboard_asset_content(
                session,
                storage,
                principal=foreign,
                asset_id=registered.asset.id,
            )
        assert hidden.value.status_code == 404

    content.path.write_bytes(b"corrupt")
    with session_factory() as session, pytest.raises(DashboardAssetError) as corrupt:
        get_dashboard_asset_content(
            session,
            storage,
            principal=viewer,
            asset_id=registered.asset.id,
        )
    assert corrupt.value.code == "dashboard_asset_storage_integrity_error"


def test_edit_permission_is_checked_before_upload_is_read(
    asset_store: tuple[
        sessionmaker[Session], LocalContentAddressedStorage, dict[str, UUID], Engine
    ],
) -> None:
    session_factory, storage, ids, _engine = asset_store
    viewer = _principal(
        workspace_id=ids["workspace"],
        user_id=ids["owner"],
        permissions=frozenset({"dashboards:view"}),
    )
    with session_factory() as session, pytest.raises(DashboardAssetError) as captured:
        register_dashboard_asset(
            session,
            storage,
            principal=viewer,
            original_name="blocked.png",
            declared_media_type="image/png",
            stream=UnreadableStream(b"not read"),
        )
    assert captured.value.status_code == 403


@pytest.mark.parametrize(
    ("filename", "media_type", "content", "expected_code"),
    [
        ("fake.png", "image/jpeg", _image_bytes("PNG"), "dashboard_asset_media_type_mismatch"),
        (
            "vector.svg",
            "image/svg+xml",
            b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            "dashboard_asset_content_invalid",
        ),
        ("broken.png", "image/png", b"not-an-image", "dashboard_asset_content_invalid"),
        ("bitmap.bmp", "image/bmp", _image_bytes("BMP"), "dashboard_asset_format_unsupported"),
    ],
)
def test_rejects_mime_spoof_svg_damage_and_unsupported_formats(
    asset_store: tuple[
        sessionmaker[Session], LocalContentAddressedStorage, dict[str, UUID], Engine
    ],
    filename: str,
    media_type: str,
    content: bytes,
    expected_code: str,
) -> None:
    session_factory, storage, ids, _engine = asset_store
    principal = _principal(workspace_id=ids["workspace"], user_id=ids["owner"])
    with session_factory() as session, pytest.raises(DashboardAssetError) as captured:
        register_dashboard_asset(
            session,
            storage,
            principal=principal,
            original_name=filename,
            declared_media_type=media_type,
            stream=BytesIO(content),
        )
    assert captured.value.code == expected_code


def test_rejects_ten_mb_and_forty_million_pixel_limits(
    asset_store: tuple[
        sessionmaker[Session], LocalContentAddressedStorage, dict[str, UUID], Engine
    ],
) -> None:
    session_factory, storage, ids, _engine = asset_store
    principal = _principal(workspace_id=ids["workspace"], user_id=ids["owner"])
    with session_factory() as session, pytest.raises(DashboardAssetError) as too_large:
        register_dashboard_asset(
            session,
            storage,
            principal=principal,
            original_name="large.png",
            declared_media_type="image/png",
            stream=BytesIO(b"x" * (MAX_DASHBOARD_ASSET_BYTES + 1)),
        )
    assert too_large.value.code == "dashboard_asset_too_large"

    oversized_dimensions = bytearray(_image_bytes("PNG", size=(1, 1)))
    oversized_dimensions[16:24] = struct.pack(">II", 8000, 6000)
    oversized_dimensions[29:33] = struct.pack(">I", zlib.crc32(oversized_dimensions[12:29]))
    with session_factory() as session, pytest.raises(DashboardAssetError) as dimensions:
        register_dashboard_asset(
            session,
            storage,
            principal=principal,
            original_name="dimensions.png",
            declared_media_type="image/png",
            stream=BytesIO(oversized_dimensions),
        )
    assert dimensions.value.code == "dashboard_asset_dimensions_exceeded"

    animated = _animated_gif_bytes(size=(2048, 2048), frame_count=10)
    assert len(animated) < MAX_DASHBOARD_ASSET_BYTES
    with session_factory() as session, pytest.raises(DashboardAssetError) as frames:
        register_dashboard_asset(
            session,
            storage,
            principal=principal,
            original_name="many-frames.gif",
            declared_media_type="image/gif",
            stream=BytesIO(animated),
        )
    assert frames.value.code == "dashboard_asset_dimensions_exceeded"


def test_dashboard_asset_http_routes_return_metadata_duplicate_and_inline_content(
    asset_store: tuple[
        sessionmaker[Session], LocalContentAddressedStorage, dict[str, UUID], Engine
    ],
) -> None:
    session_factory, storage, ids, _engine = asset_store
    actor = _principal(workspace_id=ids["workspace"], user_id=ids["owner"])
    application = FastAPI()
    application.include_router(router, prefix="/dashboard-assets")

    def session_dependency() -> Generator[Session]:
        with session_factory() as session:
            yield session

    application.dependency_overrides[get_database_session] = session_dependency
    application.dependency_overrides[get_file_storage] = lambda: storage
    application.dependency_overrides[get_query_principal] = lambda: actor
    image = _image_bytes("PNG")
    with TestClient(application) as client:
        uploaded = cast(
            Response,
            client.post(
                "/dashboard-assets",
                files={"file": ("chart.png", image, "image/png")},
            ),
        )
        duplicate = cast(
            Response,
            client.post(
                "/dashboard-assets",
                files={"file": ("chart-copy.png", image, "image/png")},
            ),
        )
        listed = cast(Response, client.get("/dashboard-assets?offset=0&limit=10"))
        asset_id = uploaded.json()["id"]
        content = cast(Response, client.get(f"/dashboard-assets/{asset_id}/content"))

    assert uploaded.status_code == 201
    assert uploaded.json()["duplicate"] is False
    assert uploaded.json()["filename"] == "chart.png"
    assert uploaded.json()["content_type"] == "image/png"
    assert uploaded.json()["width"] == 3
    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate"] is True
    assert listed.json()["total"] == 1
    assert content.content == image
    assert content.headers["content-type"] == "image/png"
    assert content.headers["content-disposition"].startswith("inline;")
