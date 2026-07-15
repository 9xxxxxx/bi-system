# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response
from openpyxl import Workbook
from sqlalchemy.engine import Engine


@pytest.fixture
def source_file_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Path]]:
    database_path = tmp_path / "api.db"
    storage_root = tmp_path / "uploads"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("BI_UPLOAD_MAX_BYTES", "100000")
    monkeypatch.setenv("BI_PREVIEW_MAX_ROWS", "2")
    clear_settings_cache()
    application = create_app()

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        yield client, storage_root

    clear_settings_cache()


def test_upload_get_duplicate_and_preview_csv(
    source_file_client: tuple[TestClient, Path],
) -> None:
    client, storage_root = source_file_client
    content = (
        "城市,数量,占比,启用,日期\n"
        "北京,10,1.5,true,2026-07-15\n"
        "上海,,2.0,false,2026-07-16\n"
        "广州,30,3.5,true,2026-07-17\n"
    ).encode("utf-8-sig")

    upload = cast(
        Response,
        client.post(
            "/api/v1/source-files",
            files={"file": ("../../metrics.csv", content, "application/octet-stream")},
        ),
    )

    assert upload.status_code == 201
    uploaded = upload.json()
    assert uploaded["original_name"] == "metrics.csv"
    assert uploaded["file_kind"] == "csv"
    assert uploaded["media_type"] == "text/csv"
    assert uploaded["duplicate"] is False

    source_file_id = uploaded["id"]
    metadata = cast(Response, client.get(f"/api/v1/source-files/{source_file_id}"))
    assert metadata.status_code == 200
    assert metadata.json()["sha256"] == uploaded["sha256"]

    duplicate = cast(
        Response,
        client.post(
            "/api/v1/source-files",
            files={"file": ("renamed.csv", content, "text/csv")},
        ),
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == source_file_id
    assert duplicate.json()["duplicate"] is True

    preview = cast(
        Response,
        client.post(
            f"/api/v1/source-files/{source_file_id}/preview",
            json={"encoding": "utf-8-sig"},
        ),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["truncated"] is True
    assert [column["inferred_type"] for column in body["columns"]] == [
        "string",
        "integer",
        "decimal",
        "boolean",
        "date",
    ]
    assert len(body["rows"]) == 2
    assert len(list((storage_root / "sha256").rglob(uploaded["sha256"]))) == 1


def test_upload_and_preview_xlsx(source_file_client: tuple[TestClient, Path]) -> None:
    client, _storage_root = source_file_client
    content = BytesIO()
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "数据"
    worksheet.append(["城市", "数量"])
    worksheet.append(["北京", 10])
    workbook.create_sheet("说明")
    workbook.save(content)
    workbook.close()

    upload = cast(
        Response,
        client.post(
            "/api/v1/source-files",
            files={"file": ("metrics.xlsx", content.getvalue(), "application/zip")},
        ),
    )
    assert upload.status_code == 201
    assert upload.json()["media_type"].endswith("spreadsheetml.sheet")

    preview = cast(
        Response,
        client.post(
            f"/api/v1/source-files/{upload.json()['id']}/preview",
            json={"sheet_name": "数据"},
        ),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["sheet_names"] == ["数据", "说明"]
    assert preview.json()["selected_sheet"] == "数据"
    assert preview.json()["rows"][0] == {"column_1": "北京", "column_2": 10}


@pytest.mark.parametrize(
    ("filename", "content", "expected_status", "expected_code"),
    [
        ("legacy.xls", b"legacy", 415, "unsupported_file_type"),
        ("macro.xlsm", b"macro", 415, "unsupported_file_type"),
        ("fake.xlsx", b"not a zip", 422, "invalid_file_content"),
        ("binary.csv", b"name\x00value", 422, "invalid_file_content"),
        ("empty.csv", b"", 400, "empty_upload"),
        ("large.csv", b"x" * 100001, 413, "upload_too_large"),
    ],
    ids=["legacy-xls", "macro-xlsm", "invalid-xlsx", "binary-csv", "empty", "oversized"],
)
def test_upload_returns_actionable_file_errors(
    source_file_client: tuple[TestClient, Path],
    filename: str,
    content: bytes,
    expected_status: int,
    expected_code: str,
) -> None:
    client, _storage_root = source_file_client

    response = cast(
        Response,
        client.post(
            "/api/v1/source-files",
            files={"file": (filename, content, "application/octet-stream")},
        ),
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert response.json()["detail"]["action"]


def test_source_file_endpoints_hide_unknown_resources(
    source_file_client: tuple[TestClient, Path],
) -> None:
    client, _storage_root = source_file_client
    unknown_id = uuid4()

    metadata = cast(Response, client.get(f"/api/v1/source-files/{unknown_id}"))
    preview = cast(
        Response,
        client.post(f"/api/v1/source-files/{unknown_id}/preview", json={}),
    )

    assert metadata.status_code == 404
    assert preview.status_code == 404
    assert metadata.json()["detail"]["code"] == "source_file_not_found"
