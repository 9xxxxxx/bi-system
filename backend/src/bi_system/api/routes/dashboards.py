from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from bi_system.api.dependencies import CurrentActor, get_database_session
from bi_system.dashboards.contracts import (
    CreateDashboard,
    CreateDashboardTemplate,
    CreateDashboardTemplateVersion,
    DashboardRevisionRequest,
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
)
from bi_system.dashboards.service import (
    DashboardDetail,
    DashboardTemplateDetail,
    activate_dashboard,
    create_dashboard,
    create_dashboard_template,
    create_dashboard_template_version,
    delete_dashboard,
    get_dashboard,
    get_dashboard_template,
    instantiate_dashboard_template,
    list_dashboard_templates,
    list_dashboards,
    publish_dashboard_template,
    replace_dashboard_permissions,
    restore_dashboard,
    save_dashboard_version,
)

router = APIRouter()
template_router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
DashboardStatus = Literal["draft", "active", "archived", "deleted"]
DashboardCapability = Literal["view", "edit", "share", "export"]


class DashboardSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    status: DashboardStatus
    owner_name: str
    updated_at: datetime
    revision: int
    current_version: int
    page_count: int
    capabilities: list[DashboardCapability]


class DashboardListResponse(BaseModel):
    items: list[DashboardSummaryResponse]
    total: int
    offset: int
    limit: int


class DashboardComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component_id: UUID
    page_id: UUID
    component_type: str
    config_version: int
    config: dict[str, object]
    ordinal: int


class DashboardPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_id: UUID
    title: str
    ordinal: int
    page_filter: dict[str, object] | None
    components: list[DashboardComponentResponse]


class DashboardLayoutItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component_id: UUID
    x: int
    y: int
    width: int
    height: int
    min_width: int
    min_height: int


class DashboardLayoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    schema_version: int
    profile: Literal["desktop", "mobile"]
    columns: int
    row_height: int
    items: list[DashboardLayoutItemResponse]


class DashboardPermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject_type: Literal["user", "role", "workspace"]
    subject_id: UUID
    capability: DashboardCapability


class DashboardDetailResponse(DashboardSummaryResponse):
    current_version_id: UUID
    global_filter: dict[str, object] | None
    pages: list[DashboardPageResponse]
    layouts: list[DashboardLayoutResponse]
    permissions: list[DashboardPermissionResponse]


class DashboardTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    status: Literal["draft", "published", "archived"]
    visibility: Literal["private", "workspace"]
    owner_name: str
    revision: int
    version_id: UUID
    source_dashboard_version_id: UUID
    updated_at: datetime


class DashboardTemplateSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    latest_version_id: UUID
    page_count: int
    owner_name: str
    updated_at: datetime


class DashboardTemplateListResponse(BaseModel):
    items: list[DashboardTemplateSummaryResponse]
    total: int
    offset: int
    limit: int


@router.post("", response_model=DashboardDetailResponse, status_code=status.HTTP_201_CREATED)
def create_dashboard_endpoint(
    request_body: CreateDashboard,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardDetailResponse:
    try:
        dashboard = create_dashboard(session, principal=actor, request=request_body)
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _dashboard_response(dashboard)


@router.get("", response_model=DashboardListResponse)
def list_dashboards_endpoint(
    session: DatabaseSession,
    actor: CurrentActor,
    include_deleted: bool = False,
    dashboard_status: Annotated[
        Literal["draft", "active", "archived", "deleted"] | None,
        Query(alias="status"),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DashboardListResponse:
    try:
        page = list_dashboards(
            session,
            principal=actor,
            offset=offset,
            limit=limit,
            include_deleted=include_deleted,
            status=dashboard_status,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return DashboardListResponse(
        items=[DashboardSummaryResponse.model_validate(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.post(
    "/{dashboard_id}/versions",
    response_model=DashboardDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_dashboard_version_endpoint(
    dashboard_id: UUID,
    request_body: SaveDashboardVersion,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardDetailResponse:
    try:
        dashboard = save_dashboard_version(
            session,
            principal=actor,
            dashboard_id=dashboard_id,
            request=request_body,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _dashboard_response(dashboard)


@router.post("/{dashboard_id}/activate", response_model=DashboardDetailResponse)
def activate_dashboard_endpoint(
    dashboard_id: UUID,
    request_body: DashboardRevisionRequest,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardDetailResponse:
    try:
        dashboard = activate_dashboard(
            session,
            principal=actor,
            dashboard_id=dashboard_id,
            expected_revision=request_body.expected_revision,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _dashboard_response(dashboard)


@router.put("/{dashboard_id}/permissions", response_model=DashboardDetailResponse)
def replace_dashboard_permissions_endpoint(
    dashboard_id: UUID,
    request_body: ReplaceDashboardPermissions,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardDetailResponse:
    try:
        dashboard = replace_dashboard_permissions(
            session,
            principal=actor,
            dashboard_id=dashboard_id,
            request=request_body,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _dashboard_response(dashboard)


@router.delete("/{dashboard_id}", response_model=DashboardDetailResponse)
def delete_dashboard_endpoint(
    dashboard_id: UUID,
    expected_revision: Annotated[int, Query(ge=1)],
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardDetailResponse:
    try:
        dashboard = delete_dashboard(
            session,
            principal=actor,
            dashboard_id=dashboard_id,
            expected_revision=expected_revision,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _dashboard_response(dashboard)


@router.post("/{dashboard_id}/restore", response_model=DashboardDetailResponse)
def restore_dashboard_endpoint(
    dashboard_id: UUID,
    request_body: DashboardRevisionRequest,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardDetailResponse:
    try:
        dashboard = restore_dashboard(
            session,
            principal=actor,
            dashboard_id=dashboard_id,
            expected_revision=request_body.expected_revision,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _dashboard_response(dashboard)


@router.get("/{dashboard_id}", response_model=DashboardDetailResponse)
def read_dashboard_endpoint(
    dashboard_id: UUID,
    session: DatabaseSession,
    actor: CurrentActor,
    include_deleted: bool = False,
) -> DashboardDetailResponse:
    try:
        dashboard = get_dashboard(
            session,
            principal=actor,
            dashboard_id=dashboard_id,
            include_deleted=include_deleted,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _dashboard_response(dashboard)


@template_router.post(
    "", response_model=DashboardTemplateResponse, status_code=status.HTTP_201_CREATED
)
def create_dashboard_template_endpoint(
    request_body: CreateDashboardTemplate,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardTemplateResponse:
    try:
        template = create_dashboard_template(session, principal=actor, request=request_body)
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _template_response(template)


@template_router.get("", response_model=DashboardTemplateListResponse)
def list_dashboard_templates_endpoint(
    session: DatabaseSession,
    actor: CurrentActor,
    template_status: Annotated[
        Literal["draft", "published", "archived"], Query(alias="status")
    ] = "published",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DashboardTemplateListResponse:
    try:
        page = list_dashboard_templates(
            session,
            principal=actor,
            status=template_status,
            offset=offset,
            limit=limit,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return DashboardTemplateListResponse(
        items=[DashboardTemplateSummaryResponse.model_validate(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@template_router.post(
    "/{template_id}/versions",
    response_model=DashboardTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dashboard_template_version_endpoint(
    template_id: UUID,
    request_body: CreateDashboardTemplateVersion,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardTemplateResponse:
    try:
        template = create_dashboard_template_version(
            session,
            principal=actor,
            template_id=template_id,
            request=request_body,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _template_response(template)


@template_router.post("/{template_id}/publish", response_model=DashboardTemplateResponse)
def publish_dashboard_template_endpoint(
    template_id: UUID,
    request_body: DashboardRevisionRequest,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardTemplateResponse:
    try:
        template = publish_dashboard_template(
            session,
            principal=actor,
            template_id=template_id,
            expected_revision=request_body.expected_revision,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _template_response(template)


@template_router.post(
    "/{template_id}/instantiate",
    response_model=DashboardDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def instantiate_dashboard_template_endpoint(
    template_id: UUID,
    request_body: InstantiateDashboardTemplate,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardDetailResponse:
    try:
        dashboard = instantiate_dashboard_template(
            session,
            principal=actor,
            template_id=template_id,
            request=request_body,
        )
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _dashboard_response(dashboard)


@template_router.get("/{template_id}", response_model=DashboardTemplateResponse)
def read_dashboard_template_endpoint(
    template_id: UUID,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DashboardTemplateResponse:
    try:
        template = get_dashboard_template(session, principal=actor, template_id=template_id)
    except Exception as exc:
        raise _mapped_dashboard_error(exc) from exc
    return _template_response(template)


def _dashboard_response(dashboard: DashboardDetail) -> DashboardDetailResponse:
    return DashboardDetailResponse.model_validate(dashboard)


def _template_response(template: DashboardTemplateDetail) -> DashboardTemplateResponse:
    return DashboardTemplateResponse.model_validate(template)


def _mapped_dashboard_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DashboardNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
        action = "Refresh the dashboard list"
    elif isinstance(exc, DashboardForbiddenError):
        status_code = status.HTTP_403_FORBIDDEN
        action = "Ask the dashboard owner or workspace administrator for access"
    elif isinstance(exc, DashboardReferenceConflictError):
        status_code = status.HTTP_409_CONFLICT
        action = "Review the listed templates and keep this dashboard or retire their references"
    elif isinstance(exc, DashboardConflictError):
        status_code = status.HTTP_409_CONFLICT
        action = "Refresh the dashboard and retry against its latest revision"
    elif isinstance(exc, DashboardConfigurationError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        action = "Correct the dashboard configuration and try again"
    else:
        raise exc
    detail: dict[str, object] = {"code": exc.code, "message": str(exc), "action": action}
    if isinstance(exc, DashboardReferenceConflictError):
        detail["impact"] = {
            "resource_type": "dashboard_template",
            "count": len(exc.references),
            "items": [
                {
                    "template_id": str(reference.template_id),
                    "template_name": reference.template_name,
                    "template_version_id": str(reference.template_version_id),
                    "version": reference.version,
                }
                for reference in exc.references
            ],
        }
    return HTTPException(status_code=status_code, detail=detail)
