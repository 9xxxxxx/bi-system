from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
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


class Dashboard(Base):
    __tablename__ = "dashboards"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_dashboards_revision_positive"),
        CheckConstraint("current_version > 0", name="ck_dashboards_current_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'deleted')",
            name="ck_dashboards_status",
        ),
        Index("ix_dashboards_workspace_status", "workspace_id", "status"),
        Index("ix_dashboards_owner_user_id", "owner_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DashboardVersion(Base):
    __tablename__ = "dashboard_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_dashboard_versions_version_positive"),
        CheckConstraint(
            "base_version IS NULL OR base_version > 0",
            name="ck_dashboard_versions_base_version_positive",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_dashboard_versions_status",
        ),
        UniqueConstraint("dashboard_id", "version", name="uq_dashboard_versions_dashboard_version"),
        Index("ix_dashboard_versions_dashboard_status", "dashboard_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dashboard_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dashboards.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    base_version: Mapped[int | None] = mapped_column(Integer)
    global_filter: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DashboardPage(Base):
    __tablename__ = "dashboard_pages"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_dashboard_pages_ordinal_nonnegative"),
        UniqueConstraint("dashboard_version_id", "page_id", name="uq_dashboard_pages_version_page"),
        UniqueConstraint(
            "dashboard_version_id", "ordinal", name="uq_dashboard_pages_version_ordinal"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dashboard_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dashboard_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_filter: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DashboardComponent(Base):
    __tablename__ = "dashboard_components"
    __table_args__ = (
        CheckConstraint(
            "component_type IN ("
            "'kpi', 'trend_indicator', 'target_progress', 'detail_table', "
            "'ranking_table', 'bar', 'horizontal_bar', 'stacked_bar', 'line', "
            "'area', 'pie', 'donut', 'rich_text', 'image')",
            name="ck_dashboard_components_type",
        ),
        CheckConstraint(
            "config_schema_version > 0",
            name="ck_dashboard_components_config_version_positive",
        ),
        CheckConstraint("ordinal >= 0", name="ck_dashboard_components_ordinal_nonnegative"),
        UniqueConstraint(
            "dashboard_version_id",
            "component_id",
            name="uq_dashboard_components_version_component",
        ),
        UniqueConstraint("page_row_id", "ordinal", name="uq_dashboard_components_page_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dashboard_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dashboard_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    page_row_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dashboard_pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_type: Mapped[str] = mapped_column(String(32), nullable=False)
    config_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DashboardLayout(Base):
    __tablename__ = "dashboard_layouts"
    __table_args__ = (
        CheckConstraint("schema_version > 0", name="ck_dashboard_layouts_schema_version"),
        CheckConstraint("columns > 0", name="ck_dashboard_layouts_columns_positive"),
        CheckConstraint("row_height > 0", name="ck_dashboard_layouts_row_height_positive"),
        CheckConstraint("profile IN ('desktop', 'mobile')", name="ck_dashboard_layouts_profile"),
        UniqueConstraint(
            "dashboard_version_id", "profile", name="uq_dashboard_layouts_version_profile"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dashboard_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dashboard_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    profile: Mapped[str] = mapped_column(String(16), nullable=False)
    columns: Mapped[int] = mapped_column(Integer, nullable=False)
    row_height: Mapped[int] = mapped_column(Integer, nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DashboardPermission(Base):
    __tablename__ = "dashboard_permissions"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('user', 'role', 'workspace')",
            name="ck_dashboard_permissions_subject_type",
        ),
        CheckConstraint(
            "capability IN ('view', 'edit', 'share', 'export')",
            name="ck_dashboard_permissions_capability",
        ),
        UniqueConstraint(
            "dashboard_id",
            "subject_type",
            "subject_id",
            "capability",
            name="uq_dashboard_permissions_subject_capability",
        ),
        Index("ix_dashboard_permissions_subject", "subject_type", "subject_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dashboard_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dashboards.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    capability: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DashboardAsset(Base):
    __tablename__ = "dashboard_assets"
    __table_args__ = (
        CheckConstraint("width > 0", name="ck_dashboard_assets_width_positive"),
        CheckConstraint("height > 0", name="ck_dashboard_assets_height_positive"),
        CheckConstraint(
            "width * height <= 40000000",
            name="ck_dashboard_assets_pixel_count",
        ),
        UniqueConstraint(
            "workspace_id",
            "blob_id",
            name="uq_dashboard_assets_workspace_blob",
        ),
        Index(
            "ix_dashboard_assets_workspace_created",
            "workspace_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    blob_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("file_blobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DashboardTemplate(Base):
    __tablename__ = "dashboard_templates"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_dashboard_templates_revision_positive"),
        CheckConstraint(
            "current_version > 0", name="ck_dashboard_templates_current_version_positive"
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_dashboard_templates_status",
        ),
        CheckConstraint(
            "visibility IN ('private', 'workspace')",
            name="ck_dashboard_templates_visibility",
        ),
        Index("ix_dashboard_templates_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class DashboardTemplateVersion(Base):
    __tablename__ = "dashboard_template_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_dashboard_template_versions_version_positive"),
        UniqueConstraint(
            "template_id", "version", name="uq_dashboard_template_versions_template_version"
        ),
        Index("ix_dashboard_template_versions_source", "source_dashboard_version_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dashboard_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_dashboard_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dashboard_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
