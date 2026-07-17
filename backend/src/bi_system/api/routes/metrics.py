from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from bi_system.api.dependencies import CurrentActor, get_database_session
from bi_system.core.config import Settings, get_settings
from bi_system.identity import QueryPrincipal
from bi_system.modeling.metric_contracts import (
    CreateMetric,
    CreateMetricVersion,
    MetricExpression,
)
from bi_system.modeling.metrics import (
    MetricConfigurationError,
    MetricConflictError,
    MetricDetail,
    MetricResourceNotFoundError,
    create_metric,
    create_metric_version,
    get_metric,
    list_metrics,
)

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class MetricSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    series_id: UUID
    dataset_id: UUID
    dataset_name: str
    code: str
    name: str
    version: int
    description: str
    result_type: Literal["integer", "decimal"]
    unit: str | None
    status: Literal["draft", "active", "deprecated"]
    owner_name: str
    updated_at: datetime


class MetricDetailResponse(MetricSummaryResponse):
    formula: MetricExpression
    dimension_field_ids: list[UUID]


class MetricPageResponse(BaseModel):
    items: list[MetricSummaryResponse]
    total: int
    offset: int
    limit: int


@router.post("", response_model=MetricDetailResponse, status_code=status.HTTP_201_CREATED)
def create_metric_endpoint(
    request_body: CreateMetric,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> MetricDetailResponse:
    _require_metric_manager(actor, settings=settings)
    try:
        metric = create_metric(
            session,
            workspace_id=settings.workspace_id,
            actor_user_id=actor.user_id,
            request=request_body,
        )
    except MetricResourceNotFoundError as exc:
        raise _metric_http_error(404, "metric_resource_not_found", str(exc)) from exc
    except MetricConfigurationError as exc:
        raise _metric_http_error(422, "invalid_metric_configuration", str(exc)) from exc
    except MetricConflictError as exc:
        raise _metric_http_error(409, "metric_version_conflict", str(exc)) from exc
    return _metric_detail_response(metric)


@router.get("", response_model=MetricPageResponse)
def list_metrics_endpoint(
    session: DatabaseSession,
    settings: ApplicationSettings,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MetricPageResponse:
    page = list_metrics(
        session,
        workspace_id=settings.workspace_id,
        offset=offset,
        limit=limit,
    )
    return MetricPageResponse(
        items=[MetricSummaryResponse.model_validate(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.get("/{metric_id}", response_model=MetricDetailResponse)
def read_metric_endpoint(
    metric_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> MetricDetailResponse:
    metric = get_metric(session, workspace_id=settings.workspace_id, metric_id=metric_id)
    if metric is None:
        raise _metric_http_error(404, "metric_not_found", "Metric was not found")
    return _metric_detail_response(metric)


@router.post(
    "/{metric_id}/versions",
    response_model=MetricDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_metric_version_endpoint(
    metric_id: UUID,
    request_body: CreateMetricVersion,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> MetricDetailResponse:
    _require_metric_manager(actor, settings=settings)
    try:
        metric = create_metric_version(
            session,
            workspace_id=settings.workspace_id,
            actor_user_id=actor.user_id,
            metric_id=metric_id,
            request=request_body,
        )
    except MetricResourceNotFoundError as exc:
        raise _metric_http_error(404, "metric_not_found", str(exc)) from exc
    except MetricConfigurationError as exc:
        raise _metric_http_error(422, "invalid_metric_configuration", str(exc)) from exc
    except MetricConflictError as exc:
        raise _metric_http_error(409, "metric_version_conflict", str(exc)) from exc
    return _metric_detail_response(metric)


def _metric_detail_response(metric: MetricDetail) -> MetricDetailResponse:
    return MetricDetailResponse.model_validate(metric)


def _require_metric_manager(actor: QueryPrincipal, *, settings: Settings) -> None:
    if actor.workspace_id != settings.workspace_id or not actor.has_permission("datasets:manage"):
        raise _metric_http_error(
            status.HTTP_403_FORBIDDEN,
            "metric_manage_forbidden",
            "Dataset management permission is required",
        )


def _metric_http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "action": "Correct the metric configuration and try again",
        },
    )
