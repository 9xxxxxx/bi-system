"""ingestion foundation

Revision ID: 0002_ingestion_foundation
Revises: 0001_baseline
Create Date: 2026-07-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ingestion_foundation"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_blobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(sha256) = 64", name="ck_file_blobs_sha256_length"),
        sa.CheckConstraint("size_bytes > 0", name="ck_file_blobs_size_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_table(
        "import_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("physical_table_name", sa.String(length=63), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_import_targets_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("physical_table_name"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_import_targets_workspace_name"),
    )
    op.create_index("ix_import_targets_workspace_id", "import_targets", ["workspace_id"])
    op.create_table(
        "import_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_import_templates_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_import_templates_version_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            "version",
            name="uq_import_templates_workspace_name_version",
        ),
    )
    op.create_index("ix_import_templates_workspace_id", "import_templates", ["workspace_id"])
    op.create_table(
        "source_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("blob_id", sa.Uuid(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("file_kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("file_kind IN ('csv', 'xlsx')", name="ck_source_files_kind"),
        sa.CheckConstraint(
            "status IN ('ready', 'quarantined')",
            name="ck_source_files_status",
        ),
        sa.ForeignKeyConstraint(["blob_id"], ["file_blobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "blob_id", name="uq_source_files_workspace_blob"),
    )
    op.create_index(
        "ix_source_files_workspace_created",
        "source_files",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "import_columns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column("physical_name", sa.String(length=63), nullable=False),
        sa.Column("data_type", sa.String(length=24), nullable=False),
        sa.Column("nullable", sa.Boolean(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "data_type IN ('string', 'integer', 'decimal', 'boolean', 'date', 'datetime')",
            name="ck_import_columns_data_type",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_import_columns_ordinal_nonnegative"),
        sa.ForeignKeyConstraint(["target_id"], ["import_targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_id", "ordinal", name="uq_import_columns_target_ordinal"),
        sa.UniqueConstraint(
            "target_id",
            "physical_name",
            name="uq_import_columns_target_physical_name",
        ),
    )
    op.create_table(
        "quality_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("column_name", sa.String(length=128), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rule_type IN ('required', 'unique', 'data_type', 'length', 'range', "
            "'enum', 'regex', 'cross_field', 'business_key', 'batch_variance')",
            name="ck_quality_rules_type",
        ),
        sa.CheckConstraint(
            "severity IN ('error', 'warning')",
            name="ck_quality_rules_severity",
        ),
        sa.CheckConstraint("version > 0", name="ck_quality_rules_version_positive"),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["import_templates.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quality_rules_template_enabled",
        "quality_rules",
        ["template_id", "enabled"],
    )
    op.create_index("ix_quality_rules_workspace_id", "quality_rules", ["workspace_id"])
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("error_report_blob_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sheet_name", sa.String(length=128), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), nullable=False),
        sa.Column("valid_rows", sa.Integer(), nullable=False),
        sa.Column("error_rows", sa.Integer(), nullable=False),
        sa.Column("warning_rows", sa.Integer(), nullable=False),
        sa.Column("checkpoint_row", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_import_batches_attempt_nonnegative"),
        sa.CheckConstraint(
            "checkpoint_row >= 0",
            name="ck_import_batches_checkpoint_nonnegative",
        ),
        sa.CheckConstraint("error_rows >= 0", name="ck_import_batches_error_nonnegative"),
        sa.CheckConstraint(
            "mode IN ('append', 'upsert', 'replace')",
            name="ck_import_batches_mode",
        ),
        sa.CheckConstraint(
            "processed_rows >= 0",
            name="ck_import_batches_processed_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'partially_succeeded', "
            "'failed', 'cancelled')",
            name="ck_import_batches_status",
        ),
        sa.CheckConstraint("valid_rows >= 0", name="ck_import_batches_valid_nonnegative"),
        sa.CheckConstraint("warning_rows >= 0", name="ck_import_batches_warning_nonnegative"),
        sa.ForeignKeyConstraint(
            ["error_report_blob_id"],
            ["file_blobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["source_files.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["import_targets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["import_templates.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_batches_claim",
        "import_batches",
        ["status", "available_at", "lease_expires_at"],
    )
    op.create_index(
        "ix_import_batches_workspace_created",
        "import_batches",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "import_issue_samples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("column_name", sa.String(length=128), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("raw_value", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "row_number > 0",
            name="ck_import_issue_samples_row_positive",
        ),
        sa.CheckConstraint(
            "severity IN ('error', 'warning')",
            name="ck_import_issue_samples_severity",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["quality_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_issue_samples_batch_row",
        "import_issue_samples",
        ["batch_id", "row_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_issue_samples_batch_row", table_name="import_issue_samples")
    op.drop_table("import_issue_samples")
    op.drop_index("ix_import_batches_workspace_created", table_name="import_batches")
    op.drop_index("ix_import_batches_claim", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_index("ix_quality_rules_workspace_id", table_name="quality_rules")
    op.drop_index("ix_quality_rules_template_enabled", table_name="quality_rules")
    op.drop_table("quality_rules")
    op.drop_table("import_columns")
    op.drop_index("ix_source_files_workspace_created", table_name="source_files")
    op.drop_table("source_files")
    op.drop_index("ix_import_templates_workspace_id", table_name="import_templates")
    op.drop_table("import_templates")
    op.drop_index("ix_import_targets_workspace_id", table_name="import_targets")
    op.drop_table("import_targets")
    op.drop_table("file_blobs")
