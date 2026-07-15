"""modeling foundation

Revision ID: 0003_modeling_foundation
Revises: 0002_ingestion_foundation
Create Date: 2026-07-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_modeling_foundation"
down_revision: str | None = "0002_ingestion_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_roles_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "code", name="uq_roles_workspace_code"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_roles_workspace_name"),
    )
    op.create_index("ix_roles_workspace_status", "roles", ["workspace_id", "status"])

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "failed_login_count >= 0",
            name="ck_users_failed_login_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'locked', 'disabled')",
            name="ck_users_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "username",
            name="uq_users_workspace_username",
        ),
    )
    op.create_index("ix_users_workspace_status", "users", ["workspace_id", "status"])

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    op.create_table(
        "semantic_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'deleted')",
            name="ck_semantic_models_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_semantic_models_version_positive"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            "version",
            name="uq_semantic_models_workspace_name_version",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "series_id",
            "version",
            name="uq_semantic_models_workspace_series_version",
        ),
    )
    op.create_index(
        "ix_semantic_models_workspace_status",
        "semantic_models",
        ["workspace_id", "status"],
    )

    op.create_table(
        "semantic_model_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("semantic_model_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=63), nullable=False),
        sa.Column("source_role", sa.String(length=16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_model_sources_ordinal_nonnegative",
        ),
        sa.CheckConstraint(
            "source_role IN ('fact', 'dimension')",
            name="ck_model_sources_role",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_model_id"],
            ["semantic_models.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["import_targets.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "semantic_model_id",
            "alias",
            name="uq_model_sources_model_alias",
        ),
        sa.UniqueConstraint(
            "semantic_model_id",
            "ordinal",
            name="uq_model_sources_model_ordinal",
        ),
    )
    op.create_index(
        "ix_model_sources_target_id",
        "semantic_model_sources",
        ["target_id"],
    )

    op.create_table(
        "semantic_model_joins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("semantic_model_id", sa.Uuid(), nullable=False),
        sa.Column("left_source_id", sa.Uuid(), nullable=False),
        sa.Column("right_source_id", sa.Uuid(), nullable=False),
        sa.Column("join_type", sa.String(length=16), nullable=False),
        sa.Column("cardinality", sa.String(length=24), nullable=False),
        sa.Column("risk_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cardinality IN ('one_to_one', 'many_to_one')",
            name="ck_model_joins_cardinality",
        ),
        sa.CheckConstraint(
            "left_source_id <> right_source_id",
            name="ck_model_joins_distinct_sources",
        ),
        sa.CheckConstraint(
            "join_type IN ('inner', 'left')",
            name="ck_model_joins_type",
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_model_joins_ordinal_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["left_source_id"],
            ["semantic_model_sources.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_source_id"],
            ["semantic_model_sources.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_model_id"],
            ["semantic_models.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "semantic_model_id",
            "ordinal",
            name="uq_model_joins_model_ordinal",
        ),
    )
    op.create_index(
        "ix_model_joins_left_source",
        "semantic_model_joins",
        ["left_source_id"],
    )
    op.create_index(
        "ix_model_joins_right_source",
        "semantic_model_joins",
        ["right_source_id"],
    )

    op.create_table(
        "semantic_model_join_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("semantic_model_join_id", sa.Uuid(), nullable=False),
        sa.Column("left_column_id", sa.Uuid(), nullable=False),
        sa.Column("right_column_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_model_join_keys_ordinal_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["left_column_id"],
            ["import_columns.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["right_column_id"],
            ["import_columns.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_model_join_id"],
            ["semantic_model_joins.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "semantic_model_join_id",
            "left_column_id",
            "right_column_id",
            name="uq_model_join_keys_join_columns",
        ),
        sa.UniqueConstraint(
            "semantic_model_join_id",
            "ordinal",
            name="uq_model_join_keys_join_ordinal",
        ),
    )

    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("semantic_model_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'deleted')",
            name="ck_datasets_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_datasets_version_positive"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_model_id"],
            ["semantic_models.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            "version",
            name="uq_datasets_workspace_name_version",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "series_id",
            "version",
            name="uq_datasets_workspace_series_version",
        ),
    )
    op.create_index("ix_datasets_semantic_model", "datasets", ["semantic_model_id"])
    op.create_index(
        "ix_datasets_workspace_status",
        "datasets",
        ["workspace_id", "status"],
    )

    op.create_table(
        "dataset_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("model_source_id", sa.Uuid(), nullable=True),
        sa.Column("source_column_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("field_kind", sa.String(length=16), nullable=False),
        sa.Column("field_role", sa.String(length=16), nullable=False),
        sa.Column("data_type", sa.String(length=24), nullable=False),
        sa.Column("expression", sa.JSON(), nullable=True),
        sa.Column("format_config", sa.JSON(), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "data_type IN ('string', 'integer', 'decimal', 'boolean', 'date', 'datetime')",
            name="ck_dataset_fields_data_type",
        ),
        sa.CheckConstraint(
            "field_kind IN ('source', 'calculated')",
            name="ck_dataset_fields_kind",
        ),
        sa.CheckConstraint(
            "field_role IN ('dimension', 'measure')",
            name="ck_dataset_fields_role",
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_dataset_fields_ordinal_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_source_id"],
            ["semantic_model_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_column_id"],
            ["import_columns.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id",
            "name",
            name="uq_dataset_fields_dataset_name",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "ordinal",
            name="uq_dataset_fields_dataset_ordinal",
        ),
    )
    op.create_index(
        "ix_dataset_fields_source_column",
        "dataset_fields",
        ["source_column_id"],
    )

    op.create_table(
        "metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("formula", sa.JSON(), nullable=False),
        sa.Column("result_type", sa.String(length=24), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "result_type IN ('integer', 'decimal')",
            name="ck_metrics_result_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'deprecated', 'deleted')",
            name="ck_metrics_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_metrics_version_positive"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "code",
            "version",
            name="uq_metrics_workspace_code_version",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "series_id",
            "version",
            name="uq_metrics_workspace_series_version",
        ),
    )
    op.create_index(
        "ix_metrics_dataset_status",
        "metrics",
        ["dataset_id", "status"],
    )

    op.create_table(
        "metric_dimensions",
        sa.Column("metric_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_field_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_field_id"],
            ["dataset_fields.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["metric_id"], ["metrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("metric_id", "dataset_field_id"),
    )
    op.create_index(
        "ix_metric_dimensions_field_id",
        "metric_dimensions",
        ["dataset_field_id"],
    )

    op.create_table(
        "row_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effect", sa.String(length=16), nullable=False),
        sa.Column("expression", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="ck_row_policies_effect",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'disabled', 'deleted')",
            name="ck_row_policies_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_row_policies_version_positive"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id",
            "name",
            "version",
            name="uq_row_policies_dataset_name_version",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "series_id",
            "version",
            name="uq_row_policies_dataset_series_version",
        ),
    )
    op.create_index(
        "ix_row_policies_dataset_status",
        "row_policies",
        ["dataset_id", "status"],
    )

    op.create_table(
        "row_policy_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("row_policy_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND role_id IS NULL) OR "
            "(user_id IS NULL AND role_id IS NOT NULL)",
            name="ck_policy_assignments_one_principal",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["row_policy_id"],
            ["row_policies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "row_policy_id",
            "role_id",
            name="uq_policy_assignments_role",
        ),
        sa.UniqueConstraint(
            "row_policy_id",
            "user_id",
            name="uq_policy_assignments_user",
        ),
    )
    op.create_index(
        "ix_policy_assignments_role_id",
        "row_policy_assignments",
        ["role_id"],
    )
    op.create_index(
        "ix_policy_assignments_user_id",
        "row_policy_assignments",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_policy_assignments_user_id", table_name="row_policy_assignments")
    op.drop_index("ix_policy_assignments_role_id", table_name="row_policy_assignments")
    op.drop_table("row_policy_assignments")
    op.drop_index("ix_row_policies_dataset_status", table_name="row_policies")
    op.drop_table("row_policies")
    op.drop_index("ix_metric_dimensions_field_id", table_name="metric_dimensions")
    op.drop_table("metric_dimensions")
    op.drop_index("ix_metrics_dataset_status", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("ix_dataset_fields_source_column", table_name="dataset_fields")
    op.drop_table("dataset_fields")
    op.drop_index("ix_datasets_workspace_status", table_name="datasets")
    op.drop_index("ix_datasets_semantic_model", table_name="datasets")
    op.drop_table("datasets")
    op.drop_table("semantic_model_join_keys")
    op.drop_index("ix_model_joins_right_source", table_name="semantic_model_joins")
    op.drop_index("ix_model_joins_left_source", table_name="semantic_model_joins")
    op.drop_table("semantic_model_joins")
    op.drop_index("ix_model_sources_target_id", table_name="semantic_model_sources")
    op.drop_table("semantic_model_sources")
    op.drop_index("ix_semantic_models_workspace_status", table_name="semantic_models")
    op.drop_table("semantic_models")
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index("ix_users_workspace_status", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_roles_workspace_status", table_name="roles")
    op.drop_table("roles")
