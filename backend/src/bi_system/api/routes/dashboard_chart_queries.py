from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from bi_system.api.dependencies import CurrentActor, get_database_session
from bi_system.core.config import Settings, get_settings
from bi_system.dashboards.chart_contracts import DashboardChartQueryRequest
from bi_system.dashboards.chart_query import (
    DashboardChartQueryError,
    execute_dashboard_chart_query,
    validate_dashboard_chart_query,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class ChartColumnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slot_key: str
    query_alias: str
    resource_kind: Literal["field", "metric"]
    resource_id: UUID
    aggregate: str | None
    label: str
    data_type: str
    unit: str | None


class ResolvedFilterEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scope: Literal["global", "page", "component"]
    field_id: UUID
    field_type: Literal["date", "datetime"]
    semantic: str
    timezone: str
    start: date | datetime
    end: date | datetime
    resolved_at: datetime


class ChartQueryWarningResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    message: str


class DashboardChartValidationResponse(BaseModel):
    valid: bool
    component_id: UUID
    columns: list[ChartColumnResponse]
    dataset_version: int
    metric_version_ids: list[UUID]
    resolved_filters: list[ResolvedFilterEvidenceResponse]


class DashboardChartQueryResponse(BaseModel):
    request_id: UUID
    component_id: UUID
    columns: list[ChartColumnResponse]
    rows: list[dict[str, object]]
    truncated: bool
    elapsed_ms: float
    dataset_version: int
    metric_version_ids: list[UUID]
    source_batch_ids: list[UUID]
    resolved_filters: list[ResolvedFilterEvidenceResponse]
    warnings: list[ChartQueryWarningResponse]


@router.post("/validate", response_model=DashboardChartValidationResponse)
def validate_dashboard_chart_query_endpoint(
    request_body: DashboardChartQueryRequest,
    session: DatabaseSession,
    actor: CurrentActor,
    settings: ApplicationSettings,
) -> DashboardChartValidationResponse:
    try:
        result = validate_dashboard_chart_query(
            session,
            principal=actor,
            request=request_body,
            workspace_timezone=settings.workspace_timezone,
            timeout_seconds=settings.query_timeout_seconds,
        )
    except DashboardChartQueryError as exc:
        raise _chart_query_http_error(exc, component_id=request_body.component_id) from exc
    return DashboardChartValidationResponse.model_validate(result, from_attributes=True)


@router.post("", response_model=DashboardChartQueryResponse)
def execute_dashboard_chart_query_endpoint(
    request_body: DashboardChartQueryRequest,
    session: DatabaseSession,
    actor: CurrentActor,
    settings: ApplicationSettings,
) -> DashboardChartQueryResponse:
    try:
        result = execute_dashboard_chart_query(
            session,
            principal=actor,
            request=request_body,
            workspace_timezone=settings.workspace_timezone,
            timeout_seconds=settings.query_timeout_seconds,
        )
    except DashboardChartQueryError as exc:
        raise _chart_query_http_error(exc, component_id=request_body.component_id) from exc
    return DashboardChartQueryResponse.model_validate(result, from_attributes=True)


def _chart_query_http_error(
    exc: DashboardChartQueryError,
    *,
    component_id: UUID,
) -> HTTPException:
    if exc.code in _NOT_FOUND_CODES:
        status_code = status.HTTP_404_NOT_FOUND
    elif exc.code in _FORBIDDEN_CODES:
        status_code = status.HTTP_403_FORBIDDEN
    elif exc.code.endswith("_conflict"):
        status_code = status.HTTP_409_CONFLICT
    elif exc.code == "dataset_query_timeout":
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "action": exc.action,
            "location": {
                "component_id": str(component_id),
                "config_path": exc.config_path,
            },
        },
    )


_NOT_FOUND_CODES = frozenset(
    {
        "dashboard_not_found",
        "dashboard_page_not_found",
        "dashboard_component_not_found",
        "dataset_not_found",
        "dataset_model_not_found",
        "dataset_field_not_found",
        "dataset_source_not_found",
        "metric_not_found",
    }
)
_FORBIDDEN_CODES = frozenset({"dashboard_forbidden", "dataset_query_forbidden"})
