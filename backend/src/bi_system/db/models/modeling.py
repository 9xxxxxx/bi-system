from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
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


class SemanticModel(Base):
    __tablename__ = "semantic_models"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_semantic_models_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'deleted')",
            name="ck_semantic_models_status",
        ),
        UniqueConstraint(
            "workspace_id",
            "name",
            "version",
            name="uq_semantic_models_workspace_name_version",
        ),
        UniqueConstraint(
            "workspace_id",
            "series_id",
            "version",
            name="uq_semantic_models_workspace_series_version",
        ),
        Index("ix_semantic_models_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    series_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SemanticModelSource(Base):
    __tablename__ = "semantic_model_sources"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_model_sources_ordinal_nonnegative"),
        CheckConstraint(
            "source_role IN ('fact', 'dimension')",
            name="ck_model_sources_role",
        ),
        UniqueConstraint(
            "semantic_model_id",
            "alias",
            name="uq_model_sources_model_alias",
        ),
        UniqueConstraint(
            "semantic_model_id",
            "ordinal",
            name="uq_model_sources_model_ordinal",
        ),
        Index("ix_model_sources_target_id", "target_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    semantic_model_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("semantic_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_targets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(String(63), nullable=False)
    source_role: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SemanticModelJoin(Base):
    __tablename__ = "semantic_model_joins"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_model_joins_ordinal_nonnegative"),
        CheckConstraint(
            "join_type IN ('inner', 'left')",
            name="ck_model_joins_type",
        ),
        CheckConstraint(
            "cardinality IN ('one_to_one', 'many_to_one')",
            name="ck_model_joins_cardinality",
        ),
        CheckConstraint(
            "left_source_id <> right_source_id",
            name="ck_model_joins_distinct_sources",
        ),
        UniqueConstraint(
            "semantic_model_id",
            "ordinal",
            name="uq_model_joins_model_ordinal",
        ),
        Index("ix_model_joins_left_source", "left_source_id"),
        Index("ix_model_joins_right_source", "right_source_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    semantic_model_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("semantic_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    left_source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("semantic_model_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    right_source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("semantic_model_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    join_type: Mapped[str] = mapped_column(String(16), nullable=False)
    cardinality: Mapped[str] = mapped_column(String(24), nullable=False)
    risk_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SemanticModelJoinKey(Base):
    __tablename__ = "semantic_model_join_keys"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_model_join_keys_ordinal_nonnegative"),
        UniqueConstraint(
            "semantic_model_join_id",
            "ordinal",
            name="uq_model_join_keys_join_ordinal",
        ),
        UniqueConstraint(
            "semantic_model_join_id",
            "left_column_id",
            "right_column_id",
            name="uq_model_join_keys_join_columns",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    semantic_model_join_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("semantic_model_joins.id", ondelete="CASCADE"),
        nullable=False,
    )
    left_column_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_columns.id", ondelete="RESTRICT"),
        nullable=False,
    )
    right_column_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_columns.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_datasets_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'deleted')",
            name="ck_datasets_status",
        ),
        UniqueConstraint(
            "workspace_id",
            "name",
            "version",
            name="uq_datasets_workspace_name_version",
        ),
        UniqueConstraint(
            "workspace_id",
            "series_id",
            "version",
            name="uq_datasets_workspace_series_version",
        ),
        Index("ix_datasets_workspace_status", "workspace_id", "status"),
        Index("ix_datasets_semantic_model", "semantic_model_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    series_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    semantic_model_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("semantic_models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetField(Base):
    __tablename__ = "dataset_fields"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_dataset_fields_ordinal_nonnegative"),
        CheckConstraint(
            "field_kind IN ('source', 'calculated')",
            name="ck_dataset_fields_kind",
        ),
        CheckConstraint(
            "field_role IN ('dimension', 'measure')",
            name="ck_dataset_fields_role",
        ),
        CheckConstraint(
            "data_type IN ('string', 'integer', 'decimal', 'boolean', 'date', 'datetime')",
            name="ck_dataset_fields_data_type",
        ),
        UniqueConstraint("dataset_id", "name", name="uq_dataset_fields_dataset_name"),
        UniqueConstraint(
            "dataset_id",
            "ordinal",
            name="uq_dataset_fields_dataset_ordinal",
        ),
        Index("ix_dataset_fields_source_column", "source_column_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_source_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("semantic_model_sources.id", ondelete="RESTRICT"),
    )
    source_column_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_columns.id", ondelete="RESTRICT"),
    )
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    field_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    field_role: Mapped[str] = mapped_column(String(16), nullable=False)
    data_type: Mapped[str] = mapped_column(String(24), nullable=False)
    expression: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    format_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_metrics_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'active', 'deprecated', 'deleted')",
            name="ck_metrics_status",
        ),
        CheckConstraint(
            "result_type IN ('integer', 'decimal')",
            name="ck_metrics_result_type",
        ),
        UniqueConstraint(
            "workspace_id",
            "code",
            "version",
            name="uq_metrics_workspace_code_version",
        ),
        UniqueConstraint(
            "workspace_id",
            "series_id",
            "version",
            name="uq_metrics_workspace_series_version",
        ),
        Index("ix_metrics_dataset_status", "dataset_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    series_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    formula: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_type: Mapped[str] = mapped_column(String(24), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MetricDimension(Base):
    __tablename__ = "metric_dimensions"
    __table_args__ = (Index("ix_metric_dimensions_field_id", "dataset_field_id"),)

    metric_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("metrics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dataset_field_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_fields.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class RowPolicy(Base):
    __tablename__ = "row_policies"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_row_policies_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'active', 'disabled', 'deleted')",
            name="ck_row_policies_status",
        ),
        CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="ck_row_policies_effect",
        ),
        UniqueConstraint(
            "dataset_id",
            "name",
            "version",
            name="uq_row_policies_dataset_name_version",
        ),
        UniqueConstraint(
            "dataset_id",
            "series_id",
            "version",
            name="uq_row_policies_dataset_series_version",
        ),
        Index("ix_row_policies_dataset_status", "dataset_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    series_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effect: Mapped[str] = mapped_column(String(16), nullable=False, default="allow")
    expression: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RowPolicyAssignment(Base):
    __tablename__ = "row_policy_assignments"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND role_id IS NULL) OR "
            "(user_id IS NULL AND role_id IS NOT NULL)",
            name="ck_policy_assignments_one_principal",
        ),
        UniqueConstraint(
            "row_policy_id",
            "user_id",
            name="uq_policy_assignments_user",
        ),
        UniqueConstraint(
            "row_policy_id",
            "role_id",
            name="uq_policy_assignments_role",
        ),
        Index("ix_policy_assignments_user_id", "user_id"),
        Index("ix_policy_assignments_role_id", "role_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    row_policy_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("row_policies.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    role_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
