from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bi_system.db.base import Base
from bi_system.db.models import (
    FileBlob,
    ImportBatch,
    ImportColumn,
    ImportIssueSample,
    ImportTarget,
    ImportTemplate,
    QualityRule,
    SourceFile,
)
from bi_system.db.session import create_database_engine, create_session_factory
from sqlalchemy.exc import IntegrityError

EXPECTED_INGESTION_TABLES = {
    "file_blobs",
    "import_batches",
    "import_columns",
    "import_issue_samples",
    "import_targets",
    "import_templates",
    "quality_rules",
    "source_files",
}


def test_ingestion_metadata_contains_expected_tables() -> None:
    assert EXPECTED_INGESTION_TABLES.issubset(Base.metadata.tables)


def test_ingestion_models_round_trip_on_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "models.db"
    engine = create_database_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()

    try:
        with session_factory.begin() as session:
            blob = FileBlob(
                sha256="a" * 64,
                size_bytes=128,
                media_type="text/csv",
                storage_key="sha256/aa/aa/" + "a" * 64,
            )
            session.add(blob)
            session.flush()

            source_file = SourceFile(
                workspace_id=workspace_id,
                blob_id=blob.id,
                original_name="城市.csv",
                file_kind="csv",
                status="ready",
            )
            template = ImportTemplate(
                workspace_id=workspace_id,
                name="城市模板",
                version=1,
                status="active",
                configuration={"header_row": 1},
            )
            target = ImportTarget(
                workspace_id=workspace_id,
                name="城市数据",
                physical_table_name="data_city_001",
                status="active",
            )
            session.add_all([source_file, template, target])
            session.flush()

            column = ImportColumn(
                target_id=target.id,
                source_name="城市",
                physical_name="city",
                data_type="string",
                nullable=False,
                ordinal=0,
            )
            rule = QualityRule(
                workspace_id=workspace_id,
                template_id=template.id,
                name="城市必填",
                rule_type="required",
                severity="error",
                column_name="城市",
                parameters={},
                version=1,
                enabled=True,
            )
            session.add_all([column, rule])
            session.flush()

            batch = ImportBatch(
                workspace_id=workspace_id,
                source_file_id=source_file.id,
                template_id=template.id,
                target_id=target.id,
                mode="append",
                status="pending",
                configuration={"encoding": "utf-8-sig"},
            )
            session.add(batch)
            session.flush()
            session.add(
                ImportIssueSample(
                    batch_id=batch.id,
                    rule_id=rule.id,
                    row_number=2,
                    column_name="城市",
                    severity="error",
                    code="required",
                    message="城市不能为空",
                    raw_value="",
                ),
            )
            batch_id = batch.id

        with session_factory() as session:
            loaded = session.get(ImportBatch, batch_id)
            assert loaded is not None
            assert loaded.workspace_id == workspace_id
            assert loaded.configuration == {"encoding": "utf-8-sig"}
            assert loaded.processed_rows == 0
            assert loaded.cancellation_requested is False
    finally:
        engine.dispose()


def test_ingestion_status_constraint_rejects_unknown_value(tmp_path: Path) -> None:
    database_path = tmp_path / "constraints.db"
    engine = create_database_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            blob = FileBlob(
                sha256="b" * 64,
                size_bytes=64,
                media_type="text/csv",
                storage_key="sha256/bb/bb/" + "b" * 64,
            )
            session.add(blob)
            session.flush()
            session.add(
                SourceFile(
                    workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
                    blob_id=blob.id,
                    original_name="invalid.csv",
                    file_kind="csv",
                    status="unknown",
                ),
            )

            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()
