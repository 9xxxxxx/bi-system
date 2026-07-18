"""dashboard foundation

Revision ID: 0005_dashboard_foundation
Revises: 0004_identity_sessions
Create Date: 2026-07-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_dashboard_foundation"
down_revision: str | None = "0004_identity_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'deleted')",
            name="ck_dashboards_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_dashboards_revision_positive"),
        sa.CheckConstraint(
            "current_version > 0",
            name="ck_dashboards_current_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dashboards_workspace_status",
        "dashboards",
        ["workspace_id", "status"],
    )
    op.create_index("ix_dashboards_owner_user_id", "dashboards", ["owner_user_id"])

    op.create_table(
        "dashboard_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=True),
        sa.Column("global_filter", sa.JSON(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_dashboard_versions_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_dashboard_versions_version_positive"),
        sa.CheckConstraint(
            "base_version IS NULL OR base_version > 0",
            name="ck_dashboard_versions_base_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["dashboards.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dashboard_id",
            "version",
            name="uq_dashboard_versions_dashboard_version",
        ),
    )
    op.create_index(
        "ix_dashboard_versions_dashboard_status",
        "dashboard_versions",
        ["dashboard_id", "status"],
    )

    op.create_table(
        "dashboard_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_version_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_filter", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_dashboard_pages_ordinal_nonnegative"),
        sa.ForeignKeyConstraint(
            ["dashboard_version_id"],
            ["dashboard_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dashboard_version_id",
            "page_id",
            name="uq_dashboard_pages_version_page",
        ),
        sa.UniqueConstraint(
            "dashboard_version_id",
            "ordinal",
            name="uq_dashboard_pages_version_ordinal",
        ),
    )

    op.create_table(
        "dashboard_components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_version_id", sa.Uuid(), nullable=False),
        sa.Column("page_row_id", sa.Uuid(), nullable=False),
        sa.Column("component_id", sa.Uuid(), nullable=False),
        sa.Column("component_type", sa.String(length=32), nullable=False),
        sa.Column("config_schema_version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "component_type IN ("
            "'kpi', 'trend_indicator', 'target_progress', 'detail_table', "
            "'ranking_table', 'bar', 'horizontal_bar', 'stacked_bar', 'line', "
            "'area', 'pie', 'donut', 'rich_text', 'image')",
            name="ck_dashboard_components_type",
        ),
        sa.CheckConstraint(
            "config_schema_version > 0",
            name="ck_dashboard_components_config_version_positive",
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_dashboard_components_ordinal_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["page_row_id"],
            ["dashboard_pages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_version_id"],
            ["dashboard_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dashboard_version_id",
            "component_id",
            name="uq_dashboard_components_version_component",
        ),
        sa.UniqueConstraint(
            "page_row_id",
            "ordinal",
            name="uq_dashboard_components_page_ordinal",
        ),
    )

    op.create_table(
        "dashboard_layouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_version_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("profile", sa.String(length=16), nullable=False),
        sa.Column("columns", sa.Integer(), nullable=False),
        sa.Column("row_height", sa.Integer(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_dashboard_layouts_schema_version",
        ),
        sa.CheckConstraint(
            "columns > 0",
            name="ck_dashboard_layouts_columns_positive",
        ),
        sa.CheckConstraint(
            "row_height > 0",
            name="ck_dashboard_layouts_row_height_positive",
        ),
        sa.CheckConstraint(
            "profile IN ('desktop', 'mobile')",
            name="ck_dashboard_layouts_profile",
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_version_id"],
            ["dashboard_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dashboard_version_id",
            "profile",
            name="uq_dashboard_layouts_version_profile",
        ),
    )

    op.create_table(
        "dashboard_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('private', 'workspace')",
            name="ck_dashboard_templates_visibility",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_dashboard_templates_status",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_dashboard_templates_revision_positive",
        ),
        sa.CheckConstraint(
            "current_version > 0",
            name="ck_dashboard_templates_current_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dashboard_templates_workspace_status",
        "dashboard_templates",
        ["workspace_id", "status"],
    )

    op.create_table(
        "dashboard_template_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_dashboard_version_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version > 0",
            name="ck_dashboard_template_versions_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_dashboard_version_id"],
            ["dashboard_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["dashboard_templates.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "version",
            name="uq_dashboard_template_versions_template_version",
        ),
    )
    op.create_index(
        "ix_dashboard_template_versions_source",
        "dashboard_template_versions",
        ["source_dashboard_version_id"],
    )

    op.create_table(
        "dashboard_permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=16), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "subject_type IN ('user', 'role', 'workspace')",
            name="ck_dashboard_permissions_subject_type",
        ),
        sa.CheckConstraint(
            "capability IN ('view', 'edit', 'share', 'export')",
            name="ck_dashboard_permissions_capability",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["dashboards.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dashboard_id",
            "subject_type",
            "subject_id",
            "capability",
            name="uq_dashboard_permissions_subject_capability",
        ),
    )
    op.create_index(
        "ix_dashboard_permissions_subject",
        "dashboard_permissions",
        ["subject_type", "subject_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_permissions_subject", table_name="dashboard_permissions")
    op.drop_table("dashboard_permissions")
    op.drop_index(
        "ix_dashboard_template_versions_source",
        table_name="dashboard_template_versions",
    )
    op.drop_table("dashboard_template_versions")
    op.drop_index(
        "ix_dashboard_templates_workspace_status",
        table_name="dashboard_templates",
    )
    op.drop_table("dashboard_templates")
    op.drop_table("dashboard_layouts")
    op.drop_table("dashboard_components")
    op.drop_table("dashboard_pages")
    op.drop_index(
        "ix_dashboard_versions_dashboard_status",
        table_name="dashboard_versions",
    )
    op.drop_table("dashboard_versions")
    op.drop_index("ix_dashboards_owner_user_id", table_name="dashboards")
    op.drop_index("ix_dashboards_workspace_status", table_name="dashboards")
    op.drop_table("dashboards")
