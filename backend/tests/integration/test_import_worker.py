# pyright: reportAny=false, reportPrivateUsage=false, reportUnknownMemberType=false
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_database_session, get_file_storage
from bi_system.core.config import Settings, get_settings
from bi_system.db.base import Base
from bi_system.db.models import FileBlob, ImportBatch, ImportIssueSample, ImportTarget
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion import worker as worker_module
from bi_system.ingestion.batch_contracts import CreateImportBatch
from bi_system.ingestion.batches import (
    cancel_import_batch,
    claim_next_import_batch,
    confirm_import_batch_warnings,
    create_import_batch,
    retry_import_batch,
)
from bi_system.ingestion.domain import ImportMode
from bi_system.ingestion.files import register_source_file
from bi_system.ingestion.storage import LocalContentAddressedStorage
from bi_system.ingestion.target_tables import build_target_table, read_active_rows
from bi_system.ingestion.template_contracts import CreateImportTemplate, ImportTemplateDefinition
from bi_system.ingestion.templates import create_import_template
from bi_system.ingestion.worker import process_import_batch, run_next_import_batch
from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class WorkerTestContext:
    engine: Engine
    session_factory: sessionmaker[Session]
    storage: LocalContentAddressedStorage
    settings: Settings
    workspace_id: UUID


@pytest.fixture
def worker_context(tmp_path: Path) -> Iterator[WorkerTestContext]:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'worker.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    storage_root = tmp_path / "uploads"
    storage = LocalContentAddressedStorage(storage_root, max_bytes=1_000_000)
    workspace_id = uuid4()
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'worker.db').as_posix()}",
        storage_root=storage_root,
        upload_max_bytes=1_000_000,
        xlsx_max_uncompressed_bytes=10_000_000,
        import_max_rows=100,
        import_chunk_rows=2,
        preview_max_rows=2,
        import_issue_sample_limit=10,
        import_worker_lease_seconds=30,
        workspace_id=workspace_id,
    )
    yield WorkerTestContext(
        engine=engine,
        session_factory=session_factory,
        storage=storage,
        settings=settings,
        workspace_id=workspace_id,
    )
    engine.dispose()


def base_definition(*, warning_rule: bool = False) -> ImportTemplateDefinition:
    quality_rules: list[dict[str, object]] = []
    if warning_rule:
        quality_rules.append(
            {
                "name": "金额预警",
                "rule_type": "range",
                "severity": "warning",
                "column_name": "amount",
                "parameters": {"maximum": 100},
            },
        )
    return ImportTemplateDefinition.model_validate(
        {
            "file_kind": "csv",
            "columns": [
                {
                    "source_key": "column_1",
                    "source_name": "城市",
                    "target_name": "city",
                    "data_type": "string",
                    "nullable": False,
                },
                {
                    "source_key": "column_2",
                    "source_name": "金额",
                    "target_name": "amount",
                    "data_type": "decimal",
                },
            ],
            "business_key": ["city"],
            "quality_rules": quality_rules,
        },
    )


def create_batch(
    context: WorkerTestContext,
    *,
    csv_text: str,
    definition: ImportTemplateDefinition | None = None,
    mode: str = "append",
    target_id: UUID | None = None,
    target_name: str | None = None,
    warnings_confirmed: bool = False,
) -> tuple[UUID, UUID, ImportTemplateDefinition]:
    selected_definition = definition or base_definition()
    with context.session_factory() as session:
        registered = register_source_file(
            session,
            context.storage,
            workspace_id=context.workspace_id,
            original_name=f"source-{uuid4()}.csv",
            stream=BytesIO(csv_text.encode("utf-8-sig")),
            xlsx_max_uncompressed_bytes=context.settings.xlsx_max_uncompressed_bytes,
            xlsx_max_compression_ratio=context.settings.xlsx_max_compression_ratio,
        )
        request = CreateImportBatch(
            source_file_id=registered.source_file.id,
            definition=selected_definition,
            target_id=target_id,
            target_name=target_name or (None if target_id else f"target-{uuid4()}"),
            mode=ImportMode(mode),
            warnings_confirmed=warnings_confirmed,
        )
        stored = create_import_batch(
            session,
            workspace_id=context.workspace_id,
            request=request,
        )
        return stored.batch.id, stored.target.id, selected_definition


def active_rows(
    context: WorkerTestContext,
    target_id: UUID,
    definition: ImportTemplateDefinition,
) -> list[dict[str, object]]:
    with context.session_factory() as session:
        target = stored_target(session, target_id)
        table = build_target_table(target, definition)
        return [dict(row) for row in read_active_rows(session, table)]


def stored_target(session: Session, target_id: UUID) -> ImportTarget:
    target = session.get(ImportTarget, target_id)
    assert target is not None
    return target


def run_worker(context: WorkerTestContext) -> ImportBatch:
    batch = run_next_import_batch(
        context.engine,
        context.session_factory,
        context.storage,
        context.settings,
        worker_id="test-worker",
    )
    assert batch is not None
    return batch


def test_worker_supports_append_replace_and_upsert(worker_context: WorkerTestContext) -> None:
    first_batch_id, target_id, definition = create_batch(
        worker_context,
        csv_text="城市,金额\n北京,10\n上海,20\n",
    )
    first = run_worker(worker_context)
    assert first.id == first_batch_id
    assert first.status == "succeeded"

    create_batch(
        worker_context,
        csv_text="城市,金额\n广州,30\n",
        target_id=target_id,
    )
    assert run_worker(worker_context).status == "succeeded"
    assert {
        row["city"]: row["amount"] for row in active_rows(worker_context, target_id, definition)
    } == {"北京": 10, "上海": 20, "广州": 30}

    create_batch(
        worker_context,
        csv_text="城市,金额\n深圳,40\n",
        definition=definition,
        mode="replace",
        target_id=target_id,
    )
    assert run_worker(worker_context).status == "succeeded"
    assert [row["city"] for row in active_rows(worker_context, target_id, definition)] == ["深圳"]

    create_batch(
        worker_context,
        csv_text="城市,金额\n深圳,45\n成都,50\n",
        definition=definition,
        mode="upsert",
        target_id=target_id,
    )
    assert run_worker(worker_context).status == "succeeded"
    rows = active_rows(worker_context, target_id, definition)
    assert sorted((row["city"], row["amount"]) for row in rows) == [
        ("成都", 50),
        ("深圳", 45),
    ]


def test_worker_imports_xlsx_using_stored_template(worker_context: WorkerTestContext) -> None:
    definition = ImportTemplateDefinition.model_validate(
        {
            "file_kind": "xlsx",
            "sheet_name": "数据",
            "columns": [
                {
                    "source_key": "column_1",
                    "source_name": "城市",
                    "target_name": "city",
                    "data_type": "string",
                    "nullable": False,
                },
                {
                    "source_key": "column_2",
                    "source_name": "金额",
                    "target_name": "amount",
                    "data_type": "decimal",
                    "nullable": False,
                },
                {
                    "source_key": "column_3",
                    "source_name": "日期",
                    "target_name": "report_date",
                    "data_type": "date",
                    "nullable": False,
                },
            ],
            "business_key": ["city", "report_date"],
        },
    )
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "数据"
    worksheet.append(["城市", "金额", "日期"])
    worksheet.append(["北京", 120.5, "2026-07-15"])
    worksheet.append(["上海", 88, "2026-07-16"])
    content = BytesIO()
    workbook.save(content)
    workbook.close()
    content.seek(0)

    with worker_context.session_factory() as session:
        template = create_import_template(
            session,
            workspace_id=worker_context.workspace_id,
            request=CreateImportTemplate(name="城市日报", definition=definition),
        )
        source = register_source_file(
            session,
            worker_context.storage,
            workspace_id=worker_context.workspace_id,
            original_name="城市日报.xlsx",
            stream=content,
            xlsx_max_uncompressed_bytes=worker_context.settings.xlsx_max_uncompressed_bytes,
            xlsx_max_compression_ratio=worker_context.settings.xlsx_max_compression_ratio,
        )
        stored = create_import_batch(
            session,
            workspace_id=worker_context.workspace_id,
            request=CreateImportBatch(
                source_file_id=source.source_file.id,
                template_id=template.template.id,
                target_name="城市日报数据",
                mode=ImportMode.APPEND,
            ),
        )

    result = run_worker(worker_context)

    assert result.id == stored.batch.id
    assert result.status == "succeeded"
    rows = active_rows(worker_context, stored.target.id, definition)
    assert [(row["city"], row["amount"], str(row["report_date"])) for row in rows] == [
        ("北京", 120.5, "2026-07-15"),
        ("上海", 88, "2026-07-16"),
    ]


def test_quality_errors_block_activation_and_store_samples(
    worker_context: WorkerTestContext,
) -> None:
    batch_id, target_id, definition = create_batch(
        worker_context,
        csv_text="城市,金额\n" + ",10\n" * 12,
    )

    result = run_worker(worker_context)

    assert result.status == "failed"
    assert result.error_code == "quality_errors"
    assert result.error_rows == 12
    assert result.error_report_blob_id is not None
    assert active_rows(worker_context, target_id, definition) == []
    with worker_context.session_factory() as session:
        issue_count = session.scalar(
            select(func.count())
            .select_from(ImportIssueSample)
            .where(ImportIssueSample.batch_id == batch_id),
        )
        assert issue_count == 10
        report_blob = session.get(FileBlob, result.error_report_blob_id)
        assert report_blob is not None
        report_text = worker_context.storage.path_for(report_blob.storage_key).read_text(
            encoding="utf-8-sig",
        )
        assert "row_number,column_name,severity,code,message,raw_value" in report_text
        assert "required" in report_text
        assert len(report_text.splitlines()) == 13

    application = create_app()

    def override_session() -> Iterator[Session]:
        with worker_context.session_factory() as session:
            yield session

    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_file_storage] = lambda: worker_context.storage
    application.dependency_overrides[get_settings] = lambda: worker_context.settings
    with TestClient(application) as client:
        issues_response = cast(
            Response,
            client.get(f"/api/v1/import-batches/{batch_id}/issues?limit=1"),
        )
        report_response = cast(
            Response,
            client.get(f"/api/v1/import-batches/{batch_id}/report"),
        )
    assert issues_response.status_code == 200, issues_response.text
    assert issues_response.json()["total"] == 10
    assert len(issues_response.json()["items"]) == 1
    assert report_response.status_code == 200
    assert report_response.content.startswith(b"\xef\xbb\xbf")
    assert "attachment" in report_response.headers["content-disposition"]


def test_warning_confirmation_requeues_and_commits_rows(
    worker_context: WorkerTestContext,
) -> None:
    definition = base_definition(warning_rule=True)
    batch_id, target_id, _definition = create_batch(
        worker_context,
        csv_text="城市,金额\n北京,200\n",
        definition=definition,
    )
    first = run_worker(worker_context)
    assert first.status == "failed"
    assert first.error_code == "warnings_confirmation_required"

    with worker_context.session_factory() as session:
        confirmed = confirm_import_batch_warnings(
            session,
            workspace_id=worker_context.workspace_id,
            batch_id=batch_id,
        )
        assert confirmed.status == "pending"

    second = run_worker(worker_context)
    assert second.status == "partially_succeeded"
    assert second.warning_rows == 1
    assert [row["city"] for row in active_rows(worker_context, target_id, definition)] == ["北京"]


def test_worker_resumes_after_committed_checkpoint(
    worker_context: WorkerTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_id, target_id, definition = create_batch(
        worker_context,
        csv_text="城市,金额\n北京,10\n上海,20\n广州,30\n深圳,40\n成都,50\n",
    )
    original_commit = cast(Callable[..., tuple[bool, int]], worker_module._commit_chunk)
    calls = 0

    def fail_on_second_chunk(*args: Any, **kwargs: Any) -> tuple[bool, int]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated worker stop")
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(worker_module, "_commit_chunk", fail_on_second_chunk)
    failed = run_worker(worker_context)
    assert failed.status == "failed"
    assert failed.checkpoint_row == 2

    with worker_context.session_factory() as session:
        retried = retry_import_batch(
            session,
            workspace_id=worker_context.workspace_id,
            batch_id=batch_id,
        )
        assert retried.processed_rows == 2

    monkeypatch.setattr(worker_module, "_commit_chunk", original_commit)
    succeeded = run_worker(worker_context)
    assert succeeded.status == "succeeded"
    assert succeeded.processed_rows == 5
    assert len(active_rows(worker_context, target_id, definition)) == 5


def test_processing_cancellation_discards_staging(worker_context: WorkerTestContext) -> None:
    batch_id, target_id, definition = create_batch(
        worker_context,
        csv_text="城市,金额\n北京,10\n上海,20\n",
    )
    with worker_context.session_factory() as session:
        claimed = claim_next_import_batch(
            session,
            worker_id="cancel-worker",
            lease_seconds=30,
        )
        assert claimed is not None
    with worker_context.session_factory() as session:
        cancellation = cancel_import_batch(
            session,
            workspace_id=worker_context.workspace_id,
            batch_id=batch_id,
        )
        assert cancellation.cancellation_requested is True

    process_import_batch(
        worker_context.engine,
        worker_context.session_factory,
        worker_context.storage,
        worker_context.settings,
        batch_id=batch_id,
        worker_id="cancel-worker",
    )

    with worker_context.session_factory() as session:
        cancelled = session.get(ImportBatch, batch_id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
    assert active_rows(worker_context, target_id, definition) == []
