from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from bi_system.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class FileBlob(Base):
    __tablename__ = "file_blobs"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_file_blobs_size_positive"),
        CheckConstraint("length(sha256) = 64", name="ck_file_blobs_sha256_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        CheckConstraint(
            "file_kind IN ('csv', 'xlsx')",
            name="ck_source_files_kind",
        ),
        CheckConstraint(
            "status IN ('ready', 'quarantined')",
            name="ck_source_files_status",
        ),
        UniqueConstraint("workspace_id", "blob_id", name="uq_source_files_workspace_blob"),
        Index("ix_source_files_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    blob_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("file_blobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImportTemplate(Base):
    __tablename__ = "import_templates"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_import_templates_version_positive"),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_import_templates_status",
        ),
        UniqueConstraint(
            "workspace_id",
            "name",
            "version",
            name="uq_import_templates_workspace_name_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QualityRule(Base):
    __tablename__ = "quality_rules"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_quality_rules_version_positive"),
        CheckConstraint(
            "severity IN ('error', 'warning')",
            name="ck_quality_rules_severity",
        ),
        CheckConstraint(
            "rule_type IN ('required', 'unique', 'data_type', 'length', 'range', "
            "'enum', 'regex', 'cross_field', 'business_key', 'batch_variance')",
            name="ck_quality_rules_type",
        ),
        Index("ix_quality_rules_template_enabled", "template_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    template_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_templates.id", ondelete="RESTRICT"),
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(128))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImportTarget(Base):
    __tablename__ = "import_targets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_import_targets_status",
        ),
        UniqueConstraint("workspace_id", "name", name="uq_import_targets_workspace_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    physical_table_name: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImportColumn(Base):
    __tablename__ = "import_columns"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_import_columns_ordinal_nonnegative"),
        CheckConstraint(
            "data_type IN ('string', 'integer', 'decimal', 'boolean', 'date', 'datetime')",
            name="ck_import_columns_data_type",
        ),
        UniqueConstraint("target_id", "ordinal", name="uq_import_columns_target_ordinal"),
        UniqueConstraint(
            "target_id",
            "physical_name",
            name="uq_import_columns_target_physical_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    target_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    physical_name: Mapped[str] = mapped_column(String(63), nullable=False)
    data_type: Mapped[str] = mapped_column(String(24), nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('append', 'upsert', 'replace')",
            name="ck_import_batches_mode",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'partially_succeeded', "
            "'failed', 'cancelled')",
            name="ck_import_batches_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_import_batches_attempt_nonnegative"),
        CheckConstraint("checkpoint_row >= 0", name="ck_import_batches_checkpoint_nonnegative"),
        CheckConstraint("processed_rows >= 0", name="ck_import_batches_processed_nonnegative"),
        CheckConstraint("valid_rows >= 0", name="ck_import_batches_valid_nonnegative"),
        CheckConstraint("error_rows >= 0", name="ck_import_batches_error_nonnegative"),
        CheckConstraint("warning_rows >= 0", name="ck_import_batches_warning_nonnegative"),
        Index("ix_import_batches_claim", "status", "available_at", "lease_expires_at"),
        Index("ix_import_batches_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_files.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_templates.id", ondelete="RESTRICT"),
    )
    target_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_targets.id", ondelete="RESTRICT"),
    )
    error_report_blob_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("file_blobs.id", ondelete="RESTRICT"),
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(128))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total_rows: Mapped[int | None] = mapped_column(Integer)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint_row: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class ImportIssueSample(Base):
    __tablename__ = "import_issue_samples"
    __table_args__ = (
        CheckConstraint("row_number > 0", name="ck_import_issue_samples_row_positive"),
        CheckConstraint(
            "severity IN ('error', 'warning')",
            name="ck_import_issue_samples_severity",
        ),
        Index("ix_import_issue_samples_batch_row", "batch_id", "row_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("quality_rules.id", ondelete="SET NULL"),
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
