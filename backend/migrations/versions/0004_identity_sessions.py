"""identity sessions

Revision ID: 0004_identity_sessions
Revises: 0003_modeling_foundation
Create Date: 2026-07-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_identity_sessions"
down_revision: str | None = "0003_modeling_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_user_sessions_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_user_sessions_token_hash_length",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_user_sessions_expires_at",
        "user_sessions",
        ["expires_at"],
    )
    op.create_index(
        "ix_user_sessions_user_revoked",
        "user_sessions",
        ["user_id", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_revoked", table_name="user_sessions")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_table("user_sessions")
