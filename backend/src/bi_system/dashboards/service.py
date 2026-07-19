from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bi_system.dashboards.contracts import (
    CreateDashboard,
    CreateDashboardTemplate,
    CreateDashboardTemplateVersion,
    DashboardComponentInput,
    DashboardLayoutInput,
    DashboardLayoutItemInput,
    DashboardPageInput,
    DashboardPermissionInput,
    InstantiateDashboardTemplate,
    ReplaceDashboardPermissions,
    SaveDashboardVersion,
)
from bi_system.dashboards.errors import (
    DashboardConfigurationError,
    DashboardConflictError,
    DashboardForbiddenError,
    DashboardNotFoundError,
    DashboardReferenceConflictError,
    DashboardTemplateReference,
)
from bi_system.db.models.dashboards import (
    Dashboard,
    DashboardComponent,
    DashboardLayout,
    DashboardPermission,
    DashboardTemplate,
    DashboardTemplateVersion,
    DashboardVersion,
    utc_now,
)
from bi_system.db.models.dashboards import (
    DashboardPage as StoredDashboardPage,
)
from bi_system.db.models.identity import Role, User
from bi_system.identity import QueryPrincipal

type DashboardCapability = Literal["view", "edit", "share", "export"]

DASHBOARD_RETENTION_DAYS = 30

_CAPABILITIES: tuple[DashboardCapability, ...] = ("view", "edit", "share", "export")
_COARSE_PERMISSION = {
    "view": "dashboards:view",
    "edit": "dashboards:edit",
    "share": "dashboards:share",
    "export": "dashboards:export",
}


@dataclass(frozen=True, slots=True)
class DashboardComponentDetail:
    component_id: UUID
    page_id: UUID
    component_type: str
    config_version: int
    config: dict[str, object]
    ordinal: int


@dataclass(frozen=True, slots=True)
class DashboardPageDetail:
    page_id: UUID
    title: str
    ordinal: int
    page_filter: dict[str, object] | None
    components: list[DashboardComponentDetail]


@dataclass(frozen=True, slots=True)
class DashboardLayoutDetail:
    schema_version: int
    profile: str
    columns: int
    row_height: int
    items: list[DashboardLayoutItemInput]


@dataclass(frozen=True, slots=True)
class DashboardPermissionDetail:
    subject_type: str
    subject_id: UUID
    capability: str


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    id: UUID
    name: str
    description: str | None
    status: str
    owner_name: str
    updated_at: datetime
    revision: int
    current_version: int
    page_count: int
    capabilities: list[DashboardCapability]


@dataclass(frozen=True, slots=True)
class DashboardDetail(DashboardSummary):
    current_version_id: UUID
    global_filter: dict[str, object] | None
    pages: list[DashboardPageDetail]
    layouts: list[DashboardLayoutDetail]
    permissions: list[DashboardPermissionDetail]


@dataclass(frozen=True, slots=True)
class DashboardListPage:
    items: list[DashboardSummary]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class DashboardTemplateDetail:
    id: UUID
    name: str
    description: str | None
    status: str
    visibility: str
    owner_name: str
    revision: int
    version_id: UUID
    source_dashboard_version_id: UUID
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DashboardTemplateSummary:
    id: UUID
    name: str
    description: str | None
    latest_version_id: UUID
    page_count: int
    owner_name: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DashboardTemplateListPage:
    items: list[DashboardTemplateSummary]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class DashboardPurgeBlock:
    dashboard_id: UUID
    references: tuple[DashboardTemplateReference, ...]


@dataclass(frozen=True, slots=True)
class DashboardPurgeResult:
    cutoff: datetime
    dry_run: bool
    candidate_ids: tuple[UUID, ...]
    eligible_ids: tuple[UUID, ...]
    purged_ids: tuple[UUID, ...]
    blocked: tuple[DashboardPurgeBlock, ...]


def create_dashboard(
    session: Session,
    *,
    principal: QueryPrincipal,
    request: CreateDashboard,
) -> DashboardDetail:
    _require_coarse(principal, "edit")
    try:
        with session.begin():
            _require_actor(session, principal)
            aggregate = _blank_aggregate()
            if request.template_version_id is not None:
                aggregate = _aggregate_from_template(
                    session,
                    principal=principal,
                    template_version_id=request.template_version_id,
                )
            detail = _create_dashboard_from_aggregate(
                session,
                principal=principal,
                name=request.name,
                description=request.description,
                aggregate=aggregate,
            )
    except IntegrityError as exc:
        raise DashboardConflictError(
            "dashboard_create_conflict", "Dashboard conflicts with an existing resource"
        ) from exc
    return detail


def list_dashboards(
    session: Session,
    *,
    principal: QueryPrincipal,
    offset: int,
    limit: int,
    include_deleted: bool = False,
    status: Literal["draft", "active", "archived", "deleted"] | None = None,
) -> DashboardListPage:
    _require_coarse(principal, "view")
    filters = [Dashboard.workspace_id == principal.workspace_id]
    if status is not None:
        filters.append(Dashboard.status == status)
    elif include_deleted:
        filters.append(Dashboard.status == "deleted")
    else:
        filters.append(Dashboard.status != "deleted")
    dashboards = list(
        session.scalars(
            select(Dashboard)
            .where(*filters)
            .order_by(Dashboard.updated_at.desc(), Dashboard.id.asc())
        ).all()
    )
    visible = [
        dashboard
        for dashboard in dashboards
        if "view" in _capabilities(session, dashboard=dashboard, principal=principal)
    ]
    items = [
        _dashboard_summary(session, dashboard=dashboard, principal=principal)
        for dashboard in visible[offset : offset + limit]
    ]
    return DashboardListPage(items=items, total=len(visible), offset=offset, limit=limit)


def get_dashboard(
    session: Session,
    *,
    principal: QueryPrincipal,
    dashboard_id: UUID,
    include_deleted: bool = False,
) -> DashboardDetail:
    dashboard = _required_dashboard(
        session,
        principal=principal,
        dashboard_id=dashboard_id,
        include_deleted=include_deleted,
    )
    _require_capability(session, dashboard=dashboard, principal=principal, capability="view")
    return _dashboard_detail(session, dashboard=dashboard, principal=principal)


def save_dashboard_version(
    session: Session,
    *,
    principal: QueryPrincipal,
    dashboard_id: UUID,
    request: SaveDashboardVersion,
) -> DashboardDetail:
    try:
        with session.begin():
            dashboard = _required_dashboard(
                session,
                principal=principal,
                dashboard_id=dashboard_id,
                lock=True,
            )
            _require_capability(
                session, dashboard=dashboard, principal=principal, capability="edit"
            )
            _require_revision(dashboard, request.expected_revision)
            if request.base_version != dashboard.current_version:
                raise DashboardConflictError(
                    "dashboard_base_version_conflict",
                    "Dashboard base version does not match the current version",
                )
            next_version = dashboard.current_version + 1
            version = DashboardVersion(
                dashboard_id=dashboard.id,
                version=next_version,
                status="draft",
                base_version=request.base_version,
                global_filter=deepcopy(request.global_filter),
                created_by_user_id=principal.user_id,
            )
            session.add(version)
            session.flush()
            _persist_version_aggregate(session, version=version, request=request)
            dashboard.current_version = next_version
            dashboard.status = "draft"
            dashboard.revision += 1
            dashboard.updated_at = utc_now()
            session.flush()
            detail = _dashboard_detail(session, dashboard=dashboard, principal=principal)
    except IntegrityError as exc:
        raise DashboardConflictError(
            "dashboard_version_conflict", "Dashboard version conflicts with existing state"
        ) from exc
    return detail


def activate_dashboard(
    session: Session,
    *,
    principal: QueryPrincipal,
    dashboard_id: UUID,
    expected_revision: int,
) -> DashboardDetail:
    with session.begin():
        dashboard = _required_dashboard(
            session,
            principal=principal,
            dashboard_id=dashboard_id,
            lock=True,
        )
        _require_capability(session, dashboard=dashboard, principal=principal, capability="edit")
        _require_revision(dashboard, expected_revision)
        current_version = _current_version(session, dashboard)
        if dashboard.status == "active" and current_version.status == "active":
            raise DashboardConflictError(
                "dashboard_activate_conflict",
                "Dashboard current version is already active",
            )
        active_versions = session.scalars(
            select(DashboardVersion).where(
                DashboardVersion.dashboard_id == dashboard.id,
                DashboardVersion.status == "active",
                DashboardVersion.id != current_version.id,
            )
        ).all()
        for version in active_versions:
            version.status = "archived"
        current_version.status = "active"
        dashboard.status = "active"
        dashboard.revision += 1
        dashboard.updated_at = utc_now()
        session.flush()
        return _dashboard_detail(session, dashboard=dashboard, principal=principal)


def delete_dashboard(
    session: Session,
    *,
    principal: QueryPrincipal,
    dashboard_id: UUID,
    expected_revision: int,
) -> DashboardDetail:
    with session.begin():
        dashboard = _required_dashboard(
            session,
            principal=principal,
            dashboard_id=dashboard_id,
            lock=True,
        )
        _require_capability(session, dashboard=dashboard, principal=principal, capability="edit")
        _require_revision(dashboard, expected_revision)
        _require_no_template_references(session, dashboard)
        dashboard.status = "deleted"
        dashboard.deleted_at = utc_now()
        dashboard.revision += 1
        dashboard.updated_at = utc_now()
        session.flush()
        return _dashboard_detail(session, dashboard=dashboard, principal=principal)


def restore_dashboard(
    session: Session,
    *,
    principal: QueryPrincipal,
    dashboard_id: UUID,
    expected_revision: int,
    now: datetime | None = None,
) -> DashboardDetail:
    resolved_now = utc_now() if now is None else _as_utc(now)
    with session.begin():
        dashboard = _required_dashboard(
            session,
            principal=principal,
            dashboard_id=dashboard_id,
            include_deleted=True,
            lock=True,
        )
        if dashboard.status != "deleted":
            raise DashboardConflictError(
                "dashboard_restore_conflict", "Only deleted dashboards can be restored"
            )
        _require_capability(session, dashboard=dashboard, principal=principal, capability="edit")
        if dashboard.deleted_at is None or _as_utc(dashboard.deleted_at) <= (
            resolved_now - timedelta(days=DASHBOARD_RETENTION_DAYS)
        ):
            raise DashboardConflictError(
                "dashboard_restore_expired",
                "Dashboard restore window has expired",
            )
        _require_revision(dashboard, expected_revision)
        dashboard.status = "draft"
        dashboard.deleted_at = None
        dashboard.revision += 1
        dashboard.updated_at = utc_now()
        session.flush()
        return _dashboard_detail(session, dashboard=dashboard, principal=principal)


def purge_expired_dashboards(
    session: Session,
    *,
    principal: QueryPrincipal,
    now: datetime | None = None,
    limit: int = 100,
    dry_run: bool = False,
) -> DashboardPurgeResult:
    if not principal.is_system_admin:
        raise DashboardForbiddenError(
            "dashboard_purge_forbidden",
            "System administrator access is required to purge dashboards",
        )
    if not 1 <= limit <= 1000:
        raise DashboardConfigurationError(
            "dashboard_purge_limit_invalid",
            "Dashboard purge limit must be between 1 and 1000",
        )
    resolved_now = utc_now() if now is None else _as_utc(now)
    cutoff = resolved_now - timedelta(days=DASHBOARD_RETENTION_DAYS)
    with session.begin():
        _require_actor(session, principal)
        statement = (
            select(Dashboard)
            .where(
                Dashboard.workspace_id == principal.workspace_id,
                Dashboard.status == "deleted",
                Dashboard.deleted_at.is_not(None),
                Dashboard.deleted_at <= cutoff,
            )
            .order_by(Dashboard.deleted_at, Dashboard.id)
            .limit(limit)
        )
        if not dry_run:
            statement = statement.with_for_update(skip_locked=True)
        candidates = list(session.scalars(statement).all())
        eligible: list[Dashboard] = []
        blocked: list[DashboardPurgeBlock] = []
        for dashboard in candidates:
            references = _dashboard_template_references(session, dashboard)
            if references:
                blocked.append(
                    DashboardPurgeBlock(
                        dashboard_id=dashboard.id,
                        references=references,
                    )
                )
            else:
                eligible.append(dashboard)
        purged_ids: tuple[UUID, ...] = ()
        if not dry_run:
            purged_ids = tuple(dashboard.id for dashboard in eligible)
            for dashboard in eligible:
                session.delete(dashboard)
            session.flush()
        return DashboardPurgeResult(
            cutoff=cutoff,
            dry_run=dry_run,
            candidate_ids=tuple(dashboard.id for dashboard in candidates),
            eligible_ids=tuple(dashboard.id for dashboard in eligible),
            purged_ids=purged_ids,
            blocked=tuple(blocked),
        )


def replace_dashboard_permissions(
    session: Session,
    *,
    principal: QueryPrincipal,
    dashboard_id: UUID,
    request: ReplaceDashboardPermissions,
) -> DashboardDetail:
    with session.begin():
        dashboard = _required_dashboard(
            session,
            principal=principal,
            dashboard_id=dashboard_id,
            lock=True,
        )
        _require_capability(session, dashboard=dashboard, principal=principal, capability="share")
        if request.expected_revision is not None:
            _require_revision(dashboard, request.expected_revision)
        _validate_permission_subjects(
            session,
            workspace_id=principal.workspace_id,
            permissions=request.permissions,
        )
        session.execute(
            delete(DashboardPermission).where(DashboardPermission.dashboard_id == dashboard.id)
        )
        session.add_all(
            [
                DashboardPermission(
                    dashboard_id=dashboard.id,
                    subject_type=permission.subject_type,
                    subject_id=permission.subject_id,
                    capability=permission.capability,
                    created_by_user_id=principal.user_id,
                )
                for permission in request.permissions
            ]
        )
        dashboard.revision += 1
        dashboard.updated_at = utc_now()
        session.flush()
        return _dashboard_detail(session, dashboard=dashboard, principal=principal)


def create_dashboard_template(
    session: Session,
    *,
    principal: QueryPrincipal,
    request: CreateDashboardTemplate,
) -> DashboardTemplateDetail:
    _require_template_management(principal)
    with session.begin():
        _require_actor(session, principal)
        source = _required_template_source_version(
            session,
            principal=principal,
            source_dashboard_version_id=request.source_dashboard_version_id,
        )
        template = DashboardTemplate(
            workspace_id=principal.workspace_id,
            name=request.name,
            description=request.description,
            status="draft",
            visibility=request.visibility,
            owner_user_id=principal.user_id,
            revision=1,
        )
        session.add(template)
        session.flush()
        version = DashboardTemplateVersion(
            template_id=template.id,
            version=1,
            source_dashboard_version_id=source.id,
            created_by_user_id=principal.user_id,
        )
        session.add(version)
        session.flush()
        return _template_detail(session, template=template, version=version)


def create_dashboard_template_version(
    session: Session,
    *,
    principal: QueryPrincipal,
    template_id: UUID,
    request: CreateDashboardTemplateVersion,
) -> DashboardTemplateDetail:
    _require_template_management(principal)
    try:
        with session.begin():
            _require_actor(session, principal)
            template = _required_template(
                session,
                principal=principal,
                template_id=template_id,
                lock=True,
            )
            _require_template_revision(template, request.expected_revision)
            if template.status != "published":
                raise DashboardConflictError(
                    "dashboard_template_version_conflict",
                    "Only published dashboard templates can create a new draft version",
                )
            source = _required_template_source_version(
                session,
                principal=principal,
                source_dashboard_version_id=request.source_dashboard_version_id,
            )
            next_version = template.current_version + 1
            version = DashboardTemplateVersion(
                template_id=template.id,
                version=next_version,
                source_dashboard_version_id=source.id,
                created_by_user_id=principal.user_id,
            )
            session.add(version)
            template.current_version = next_version
            template.status = "draft"
            template.revision += 1
            template.updated_at = utc_now()
            session.flush()
            return _template_detail(session, template=template, version=version)
    except IntegrityError as exc:
        raise DashboardConflictError(
            "dashboard_template_version_conflict",
            "Dashboard template version conflicts with existing state",
        ) from exc


def publish_dashboard_template(
    session: Session,
    *,
    principal: QueryPrincipal,
    template_id: UUID,
    expected_revision: int,
) -> DashboardTemplateDetail:
    _require_template_publish(principal)
    with session.begin():
        template = _required_template(
            session,
            principal=principal,
            template_id=template_id,
            lock=True,
        )
        _require_template_revision(template, expected_revision)
        if template.status != "draft":
            raise DashboardConflictError(
                "dashboard_template_publish_conflict",
                "Only draft dashboard templates can be published",
            )
        version = _latest_template_version(session, template)
        template.status = "published"
        template.revision += 1
        template.updated_at = utc_now()
        session.flush()
        return _template_detail(session, template=template, version=version)


def instantiate_dashboard_template(
    session: Session,
    *,
    principal: QueryPrincipal,
    template_id: UUID,
    request: InstantiateDashboardTemplate,
) -> DashboardDetail:
    _require_coarse(principal, "edit")
    try:
        with session.begin():
            _require_actor(session, principal)
            aggregate = _aggregate_from_template(
                session,
                principal=principal,
                template_version_id=request.template_version_id,
                expected_template_id=template_id,
            )
            return _create_dashboard_from_aggregate(
                session,
                principal=principal,
                name=request.name,
                description=request.description,
                aggregate=aggregate,
            )
    except IntegrityError as exc:
        raise DashboardConflictError(
            "dashboard_create_conflict", "Dashboard conflicts with an existing resource"
        ) from exc


def list_dashboard_templates(
    session: Session,
    *,
    principal: QueryPrincipal,
    status: Literal["draft", "published", "archived"] = "published",
    offset: int = 0,
    limit: int = 50,
) -> DashboardTemplateListPage:
    can_manage = principal.has_permission("dashboard_templates:manage") or principal.has_permission(
        "dashboard_templates:publish"
    )
    if status == "published":
        visibility_filter = or_(
            DashboardTemplate.visibility == "workspace",
            DashboardTemplate.owner_user_id == principal.user_id,
        )
    elif can_manage:
        visibility_filter = DashboardTemplate.workspace_id == principal.workspace_id
    else:
        visibility_filter = DashboardTemplate.owner_user_id == principal.user_id
    templates = list(
        session.scalars(
            select(DashboardTemplate)
            .where(
                DashboardTemplate.workspace_id == principal.workspace_id,
                DashboardTemplate.status == status,
                visibility_filter,
            )
            .order_by(DashboardTemplate.updated_at.desc(), DashboardTemplate.id.asc())
        ).all()
    )
    visible = templates[offset : offset + limit]
    return DashboardTemplateListPage(
        items=[_template_summary(session, template) for template in visible],
        total=len(templates),
        offset=offset,
        limit=limit,
    )


def get_dashboard_template(
    session: Session,
    *,
    principal: QueryPrincipal,
    template_id: UUID,
) -> DashboardTemplateDetail:
    template = session.scalar(
        select(DashboardTemplate).where(
            DashboardTemplate.id == template_id,
            DashboardTemplate.workspace_id == principal.workspace_id,
        )
    )
    can_manage = principal.has_permission("dashboard_templates:manage") or principal.has_permission(
        "dashboard_templates:publish"
    )
    can_view = template is not None and (
        template.owner_user_id == principal.user_id
        or can_manage
        or (template.status == "published" and template.visibility == "workspace")
    )
    if template is None or not can_view:
        raise DashboardNotFoundError(
            "dashboard_template_not_found", "Dashboard template was not found"
        )
    return _template_detail(
        session,
        template=template,
        version=_latest_template_version(session, template),
    )


def _create_dashboard_from_aggregate(
    session: Session,
    *,
    principal: QueryPrincipal,
    name: str,
    description: str | None,
    aggregate: SaveDashboardVersion,
) -> DashboardDetail:
    dashboard = Dashboard(
        workspace_id=principal.workspace_id,
        owner_user_id=principal.user_id,
        name=name,
        description=description,
        status="draft",
        revision=1,
        current_version=1,
    )
    session.add(dashboard)
    session.flush()
    version = DashboardVersion(
        dashboard_id=dashboard.id,
        version=1,
        status="draft",
        base_version=None,
        global_filter=deepcopy(aggregate.global_filter),
        created_by_user_id=principal.user_id,
    )
    session.add(version)
    session.flush()
    _persist_version_aggregate(session, version=version, request=aggregate)
    session.flush()
    return _dashboard_detail(session, dashboard=dashboard, principal=principal)


def _blank_aggregate() -> SaveDashboardVersion:
    return SaveDashboardVersion(
        base_version=1,
        expected_revision=1,
        pages=[],
        components=[],
        layouts=[
            DashboardLayoutInput(profile="desktop", items=[]),
            DashboardLayoutInput(profile="mobile", items=[]),
        ],
    )


def _persist_version_aggregate(
    session: Session,
    *,
    version: DashboardVersion,
    request: SaveDashboardVersion,
) -> None:
    page_rows: dict[UUID, StoredDashboardPage] = {}
    for page in request.pages:
        stored = StoredDashboardPage(
            dashboard_version_id=version.id,
            page_id=page.page_id,
            title=page.title,
            ordinal=page.ordinal,
            page_filter=deepcopy(page.page_filter),
        )
        session.add(stored)
        page_rows[page.page_id] = stored
    session.flush()

    next_ordinal_by_page = {page_id: 0 for page_id in page_rows}
    for component in request.components:
        page_row = page_rows.get(component.page_id)
        if page_row is None:
            raise DashboardConfigurationError(
                "dashboard_component_page_not_found",
                "Dashboard component references an unknown page",
            )
        ordinal = next_ordinal_by_page[component.page_id]
        next_ordinal_by_page[component.page_id] = ordinal + 1
        session.add(
            DashboardComponent(
                dashboard_version_id=version.id,
                component_id=component.component_id,
                page_row_id=page_row.id,
                component_type=component.component_type,
                config_schema_version=component.config_version,
                config=deepcopy(component.config),
                ordinal=ordinal,
            )
        )
    for layout in request.layouts:
        session.add(
            DashboardLayout(
                dashboard_version_id=version.id,
                schema_version=layout.schema_version,
                profile=layout.profile,
                columns=layout.resolved_columns,
                row_height=layout.row_height,
                items=[item.model_dump(mode="json") for item in layout.items],
            )
        )


def _required_dashboard(
    session: Session,
    *,
    principal: QueryPrincipal,
    dashboard_id: UUID,
    include_deleted: bool = False,
    lock: bool = False,
) -> Dashboard:
    statement = select(Dashboard).where(
        Dashboard.id == dashboard_id,
        Dashboard.workspace_id == principal.workspace_id,
    )
    if not include_deleted:
        statement = statement.where(Dashboard.status != "deleted")
    if lock:
        statement = statement.with_for_update()
    dashboard = session.scalar(statement)
    if dashboard is None:
        raise DashboardNotFoundError("dashboard_not_found", "Dashboard was not found")
    return dashboard


def _dashboard_summary(
    session: Session,
    *,
    dashboard: Dashboard,
    principal: QueryPrincipal,
) -> DashboardSummary:
    owner_name = session.scalar(select(User.display_name).where(User.id == dashboard.owner_user_id))
    if owner_name is None:
        raise DashboardConfigurationError(
            "dashboard_owner_not_found", "Dashboard owner was not found"
        )
    version = _current_version(session, dashboard)
    page_count = session.scalar(
        select(func.count(StoredDashboardPage.id)).where(
            StoredDashboardPage.dashboard_version_id == version.id
        )
    )
    return DashboardSummary(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        status=dashboard.status,
        owner_name=owner_name,
        updated_at=dashboard.updated_at,
        revision=dashboard.revision,
        current_version=dashboard.current_version,
        page_count=page_count or 0,
        capabilities=_capabilities(session, dashboard=dashboard, principal=principal),
    )


def _dashboard_detail(
    session: Session,
    *,
    dashboard: Dashboard,
    principal: QueryPrincipal,
) -> DashboardDetail:
    summary = _dashboard_summary(session, dashboard=dashboard, principal=principal)
    version = _current_version(session, dashboard)
    page_rows = list(
        session.scalars(
            select(StoredDashboardPage)
            .where(StoredDashboardPage.dashboard_version_id == version.id)
            .order_by(StoredDashboardPage.ordinal, StoredDashboardPage.page_id)
        ).all()
    )
    components = list(
        session.scalars(
            select(DashboardComponent)
            .where(DashboardComponent.dashboard_version_id == version.id)
            .order_by(DashboardComponent.page_row_id, DashboardComponent.ordinal)
        ).all()
    )
    components_by_page: dict[UUID, list[DashboardComponentDetail]] = {
        page.id: [] for page in page_rows
    }
    page_id_by_row = {page.id: page.page_id for page in page_rows}
    for component in components:
        logical_page_id = page_id_by_row.get(component.page_row_id)
        if logical_page_id is None:
            raise DashboardConfigurationError(
                "dashboard_component_page_not_found",
                "Stored dashboard component references a missing page",
            )
        components_by_page[component.page_row_id].append(
            DashboardComponentDetail(
                component_id=component.component_id,
                page_id=logical_page_id,
                component_type=component.component_type,
                config_version=component.config_schema_version,
                config=cast(dict[str, object], deepcopy(component.config)),
                ordinal=component.ordinal,
            )
        )
    pages = [
        DashboardPageDetail(
            page_id=page.page_id,
            title=page.title,
            ordinal=page.ordinal,
            page_filter=cast(dict[str, object] | None, deepcopy(page.page_filter)),
            components=components_by_page[page.id],
        )
        for page in page_rows
    ]
    layouts = [
        DashboardLayoutDetail(
            schema_version=layout.schema_version,
            profile=layout.profile,
            columns=layout.columns,
            row_height=layout.row_height,
            items=[DashboardLayoutItemInput.model_validate(item) for item in layout.items],
        )
        for layout in session.scalars(
            select(DashboardLayout)
            .where(DashboardLayout.dashboard_version_id == version.id)
            .order_by(DashboardLayout.profile)
        ).all()
    ]
    permissions = [
        DashboardPermissionDetail(
            subject_type=permission.subject_type,
            subject_id=permission.subject_id,
            capability=permission.capability,
        )
        for permission in session.scalars(
            select(DashboardPermission)
            .where(DashboardPermission.dashboard_id == dashboard.id)
            .order_by(
                DashboardPermission.subject_type,
                DashboardPermission.subject_id,
                DashboardPermission.capability,
            )
        ).all()
    ]
    return DashboardDetail(
        id=summary.id,
        name=summary.name,
        description=summary.description,
        status=summary.status,
        owner_name=summary.owner_name,
        updated_at=summary.updated_at,
        current_version=summary.current_version,
        page_count=summary.page_count,
        capabilities=summary.capabilities,
        revision=dashboard.revision,
        current_version_id=version.id,
        global_filter=cast(dict[str, object] | None, deepcopy(version.global_filter)),
        pages=pages,
        layouts=layouts,
        permissions=permissions,
    )


def _current_version(session: Session, dashboard: Dashboard) -> DashboardVersion:
    version = session.scalar(
        select(DashboardVersion).where(
            DashboardVersion.dashboard_id == dashboard.id,
            DashboardVersion.version == dashboard.current_version,
        )
    )
    if version is None:
        raise DashboardConfigurationError(
            "dashboard_current_version_not_found", "Dashboard current version was not found"
        )
    return version


def _capabilities(
    session: Session,
    *,
    dashboard: Dashboard,
    principal: QueryPrincipal,
) -> list[DashboardCapability]:
    if principal.workspace_id != dashboard.workspace_id:
        return []
    resource_capabilities: set[str]
    if principal.is_system_admin or principal.user_id == dashboard.owner_user_id:
        resource_capabilities = set(_CAPABILITIES)
    else:
        subject_conditions = [
            (DashboardPermission.subject_type == "user")
            & (DashboardPermission.subject_id == principal.user_id),
            (DashboardPermission.subject_type == "workspace")
            & (DashboardPermission.subject_id == principal.workspace_id),
        ]
        if principal.role_ids:
            subject_conditions.append(
                (DashboardPermission.subject_type == "role")
                & (DashboardPermission.subject_id.in_(principal.role_ids))
            )
        resource_capabilities = set(
            session.scalars(
                select(DashboardPermission.capability).where(
                    DashboardPermission.dashboard_id == dashboard.id,
                    or_(*subject_conditions),
                )
            ).all()
        )
    return [
        capability
        for capability in _CAPABILITIES
        if capability in resource_capabilities
        and principal.has_permission(_COARSE_PERMISSION[capability])
    ]


def _require_capability(
    session: Session,
    *,
    dashboard: Dashboard,
    principal: QueryPrincipal,
    capability: DashboardCapability,
) -> None:
    _require_coarse(principal, capability)
    if capability not in _capabilities(session, dashboard=dashboard, principal=principal):
        raise DashboardForbiddenError(
            "dashboard_forbidden", f"Dashboard {capability} capability is required"
        )


def _require_coarse(principal: QueryPrincipal, capability: DashboardCapability) -> None:
    if not principal.has_permission(_COARSE_PERMISSION[capability]):
        raise DashboardForbiddenError(
            "dashboard_forbidden", f"Dashboard {capability} permission is required"
        )


def _require_revision(dashboard: Dashboard, expected_revision: int) -> None:
    if dashboard.revision != expected_revision:
        raise DashboardConflictError(
            "dashboard_revision_conflict",
            f"Dashboard revision is {dashboard.revision}, not {expected_revision}",
        )


def _require_template_revision(
    template: DashboardTemplate,
    expected_revision: int,
) -> None:
    if template.revision != expected_revision:
        raise DashboardConflictError(
            "dashboard_template_revision_conflict",
            f"Dashboard template revision is {template.revision}, not {expected_revision}",
        )


def _require_template_management(principal: QueryPrincipal) -> None:
    if not principal.has_permission("dashboard_templates:manage"):
        raise DashboardForbiddenError(
            "dashboard_template_manage_forbidden",
            "Dashboard template management permission is required",
        )


def _require_template_publish(principal: QueryPrincipal) -> None:
    if not principal.has_permission("dashboard_templates:publish"):
        raise DashboardForbiddenError(
            "dashboard_template_publish_forbidden",
            "Dashboard template publish permission is required",
        )


def _required_template(
    session: Session,
    *,
    principal: QueryPrincipal,
    template_id: UUID,
    lock: bool = False,
) -> DashboardTemplate:
    statement = select(DashboardTemplate).where(
        DashboardTemplate.id == template_id,
        DashboardTemplate.workspace_id == principal.workspace_id,
    )
    if lock:
        statement = statement.with_for_update()
    template = session.scalar(statement)
    if template is None:
        raise DashboardNotFoundError(
            "dashboard_template_not_found", "Dashboard template was not found"
        )
    return template


def _required_template_source_version(
    session: Session,
    *,
    principal: QueryPrincipal,
    source_dashboard_version_id: UUID,
) -> DashboardVersion:
    source = session.get(DashboardVersion, source_dashboard_version_id)
    if source is None:
        raise DashboardNotFoundError(
            "dashboard_version_not_found", "Source dashboard version was not found"
        )
    dashboard = session.scalar(
        select(Dashboard).where(Dashboard.id == source.dashboard_id).with_for_update()
    )
    if (
        dashboard is None
        or dashboard.workspace_id != principal.workspace_id
        or dashboard.status == "deleted"
    ):
        raise DashboardNotFoundError(
            "dashboard_version_not_found", "Source dashboard version was not found"
        )
    _require_capability(session, dashboard=dashboard, principal=principal, capability="view")
    return source


def _dashboard_template_references(
    session: Session,
    dashboard: Dashboard,
) -> tuple[DashboardTemplateReference, ...]:
    return tuple(
        DashboardTemplateReference(
            template_id=template_id,
            template_name=template_name,
            template_version_id=template_version_id,
            version=version,
        )
        for template_id, template_name, template_version_id, version in session.execute(
            select(
                DashboardTemplate.id,
                DashboardTemplate.name,
                DashboardTemplateVersion.id,
                DashboardTemplateVersion.version,
            )
            .join(
                DashboardTemplate,
                DashboardTemplate.id == DashboardTemplateVersion.template_id,
            )
            .join(
                DashboardVersion,
                DashboardVersion.id == DashboardTemplateVersion.source_dashboard_version_id,
            )
            .where(DashboardVersion.dashboard_id == dashboard.id)
            .order_by(DashboardTemplate.id, DashboardTemplateVersion.version)
        ).all()
    )


def _require_no_template_references(session: Session, dashboard: Dashboard) -> None:
    references = _dashboard_template_references(session, dashboard)
    if references:
        raise DashboardReferenceConflictError(
            "dashboard_reference_conflict",
            "Dashboard versions are referenced by a dashboard template",
            references=references,
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_actor(session: Session, principal: QueryPrincipal) -> None:
    actor = session.scalar(
        select(User).where(
            User.id == principal.user_id,
            User.workspace_id == principal.workspace_id,
            User.status == "active",
        )
    )
    if actor is None:
        raise DashboardNotFoundError("dashboard_actor_not_found", "Actor user was not found")


def _validate_permission_subjects(
    session: Session,
    *,
    workspace_id: UUID,
    permissions: list[DashboardPermissionInput],
) -> None:
    for permission in permissions:
        if permission.subject_type == "workspace":
            if permission.subject_id != workspace_id:
                raise DashboardNotFoundError(
                    "dashboard_permission_subject_not_found",
                    "Workspace permission subject was not found",
                )
            continue
        model = User if permission.subject_type == "user" else Role
        subject = session.scalar(
            select(model).where(
                model.id == permission.subject_id, model.workspace_id == workspace_id
            )
        )
        if subject is None:
            raise DashboardNotFoundError(
                "dashboard_permission_subject_not_found",
                "Dashboard permission subject was not found",
            )


def _aggregate_from_template(
    session: Session,
    *,
    principal: QueryPrincipal,
    template_version_id: UUID,
    expected_template_id: UUID | None = None,
) -> SaveDashboardVersion:
    version = session.get(DashboardTemplateVersion, template_version_id)
    if version is None:
        raise DashboardNotFoundError(
            "dashboard_template_version_not_found", "Dashboard template version was not found"
        )
    template = session.get(DashboardTemplate, version.template_id)
    if (
        template is None
        or template.workspace_id != principal.workspace_id
        or (expected_template_id is not None and template.id != expected_template_id)
    ):
        raise DashboardNotFoundError(
            "dashboard_template_version_not_found", "Dashboard template version was not found"
        )
    version_is_published = template.status == "published" or (
        template.status == "draft" and version.version < template.current_version
    )
    if not version_is_published:
        raise DashboardConflictError(
            "dashboard_template_version_unpublished",
            "Dashboard template version is not published",
        )
    if template.visibility != "workspace" and template.owner_user_id != principal.user_id:
        raise DashboardForbiddenError(
            "dashboard_template_forbidden", "Dashboard template access is required"
        )
    source = session.get(DashboardVersion, version.source_dashboard_version_id)
    if source is None:
        raise DashboardConfigurationError(
            "dashboard_template_source_not_found", "Dashboard template source was not found"
        )
    source_dashboard = session.get(Dashboard, source.dashboard_id)
    if (
        source_dashboard is None
        or source_dashboard.workspace_id != principal.workspace_id
        or source_dashboard.status == "deleted"
    ):
        raise DashboardConfigurationError(
            "dashboard_template_source_unavailable",
            "Dashboard template source is unavailable",
        )
    return _copy_aggregate(session, source)


def _copy_aggregate(session: Session, version: DashboardVersion) -> SaveDashboardVersion:
    source_pages = list(
        session.scalars(
            select(StoredDashboardPage)
            .where(StoredDashboardPage.dashboard_version_id == version.id)
            .order_by(StoredDashboardPage.ordinal)
        ).all()
    )
    page_id_map = {page.page_id: uuid4() for page in source_pages}
    page_row_to_logical = {page.id: page.page_id for page in source_pages}
    source_components = list(
        session.scalars(
            select(DashboardComponent)
            .where(DashboardComponent.dashboard_version_id == version.id)
            .order_by(DashboardComponent.page_row_id, DashboardComponent.ordinal)
        ).all()
    )
    component_id_map = {component.component_id: uuid4() for component in source_components}
    pages = [
        DashboardPageInput(
            page_id=page_id_map[page.page_id],
            title=page.title,
            ordinal=page.ordinal,
            page_filter=cast(dict[str, object] | None, deepcopy(page.page_filter)),
        )
        for page in source_pages
    ]
    components = [
        DashboardComponentInput(
            component_id=component_id_map[component.component_id],
            page_id=page_id_map[page_row_to_logical[component.page_row_id]],
            component_type=cast(
                Literal[
                    "kpi",
                    "trend_indicator",
                    "target_progress",
                    "detail_table",
                    "ranking_table",
                    "bar",
                    "horizontal_bar",
                    "stacked_bar",
                    "line",
                    "area",
                    "pie",
                    "donut",
                    "rich_text",
                    "image",
                ],
                component.component_type,
            ),
            config_version=cast(Literal[1], component.config_schema_version),
            config=cast(dict[str, object], deepcopy(component.config)),
        )
        for component in source_components
    ]
    layouts: list[DashboardLayoutInput] = []
    for layout in session.scalars(
        select(DashboardLayout)
        .where(DashboardLayout.dashboard_version_id == version.id)
        .order_by(DashboardLayout.profile)
    ).all():
        items = [DashboardLayoutItemInput.model_validate(item) for item in layout.items]
        layouts.append(
            DashboardLayoutInput(
                schema_version=cast(Literal[1], layout.schema_version),
                profile=cast(Literal["desktop", "mobile"], layout.profile),
                columns=layout.columns,
                row_height=layout.row_height,
                items=[
                    item.model_copy(update={"component_id": component_id_map[item.component_id]})
                    for item in items
                ],
            )
        )
    return SaveDashboardVersion(
        base_version=1,
        expected_revision=1,
        global_filter=cast(dict[str, object] | None, deepcopy(version.global_filter)),
        pages=pages,
        components=components,
        layouts=layouts,
    )


def _latest_template_version(
    session: Session, template: DashboardTemplate
) -> DashboardTemplateVersion:
    version = session.scalar(
        select(DashboardTemplateVersion)
        .where(DashboardTemplateVersion.template_id == template.id)
        .order_by(DashboardTemplateVersion.version.desc())
    )
    if version is None:
        raise DashboardConfigurationError(
            "dashboard_template_version_not_found", "Dashboard template version was not found"
        )
    return version


def _template_detail(
    session: Session,
    *,
    template: DashboardTemplate,
    version: DashboardTemplateVersion,
) -> DashboardTemplateDetail:
    owner_name = session.scalar(select(User.display_name).where(User.id == template.owner_user_id))
    if owner_name is None:
        raise DashboardConfigurationError(
            "dashboard_template_owner_not_found", "Dashboard template owner was not found"
        )
    return DashboardTemplateDetail(
        id=template.id,
        name=template.name,
        description=template.description,
        status=template.status,
        visibility=template.visibility,
        owner_name=owner_name,
        revision=template.revision,
        version_id=version.id,
        source_dashboard_version_id=version.source_dashboard_version_id,
        updated_at=template.updated_at,
    )


def _template_summary(
    session: Session,
    template: DashboardTemplate,
) -> DashboardTemplateSummary:
    version = _latest_template_version(session, template)
    owner_name = session.scalar(select(User.display_name).where(User.id == template.owner_user_id))
    if owner_name is None:
        raise DashboardConfigurationError(
            "dashboard_template_owner_not_found", "Dashboard template owner was not found"
        )
    page_count = session.scalar(
        select(func.count(StoredDashboardPage.id)).where(
            StoredDashboardPage.dashboard_version_id == version.source_dashboard_version_id
        )
    )
    return DashboardTemplateSummary(
        id=template.id,
        name=template.name,
        description=template.description,
        latest_version_id=version.id,
        page_count=page_count or 0,
        owner_name=owner_name,
        updated_at=template.updated_at,
    )
