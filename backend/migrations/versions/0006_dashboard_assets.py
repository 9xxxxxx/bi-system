"""dashboard image assets

Revision ID: 0006_dashboard_assets
Revises: 0005_dashboard_foundation
Create Date: 2026-07-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_dashboard_assets"
down_revision: str | None = "0005_dashboard_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("blob_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "width > 0",
            name="ck_dashboard_assets_width_positive",
        ),
        sa.CheckConstraint(
            "height > 0",
            name="ck_dashboard_assets_height_positive",
        ),
        sa.CheckConstraint(
            "width * height <= 40000000",
            name="ck_dashboard_assets_pixel_count",
        ),
        sa.ForeignKeyConstraint(
            ["blob_id"],
            ["file_blobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "blob_id",
            name="uq_dashboard_assets_workspace_blob",
        ),
    )
    op.create_index(
        "ix_dashboard_assets_workspace_created",
        "dashboard_assets",
        ["workspace_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dashboard_assets_workspace_created",
        table_name="dashboard_assets",
    )
    op.drop_table("dashboard_assets")
