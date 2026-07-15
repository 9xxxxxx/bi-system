from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from bi_system.api.dependencies import CurrentActor, get_database_session
from bi_system.core.config import Settings, get_settings
from bi_system.identity import QueryPrincipal
from bi_system.modeling.dataset_contracts import CreateDataset, CreateDatasetVersion
from bi_system.modeling.datasets import (
    DatasetConfigurationError,
    DatasetDetail,
    DatasetResourceNotFoundError,
    create_dataset,
    create_dataset_version,
    get_dataset_detail,
    list_datasets,
)

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class DatasetSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    status: Literal["draft", "active", "archived"]
    source_count: int
    field_count: int
    metric_count: int
    owner_name: str
    updated_at: datetime


class DatasetPageResponse(BaseModel):
    items: list[DatasetSummaryResponse]
    total: int
    offset: int
    limit: int


class DatasetFieldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_source_id: UUID | None
    source_column_id: UUID | None
    name: str
    label: str
    field_kind: Literal["source", "calculated"]
    role: Literal["dimension", "measure"]
    data_type: Literal["string", "integer", "decimal", "boolean", "date", "datetime"]
    hidden: bool
    ordinal: int


class DatasetDetailResponse(DatasetSummaryResponse):
    semantic_model_id: UUID
    series_id: UUID
    version: int
    fields: list[DatasetFieldResponse]


@router.post("", response_model=DatasetDetailResponse, status_code=status.HTTP_201_CREATED)
def create_dataset_endpoint(
    request_body: CreateDataset,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> DatasetDetailResponse:
    _require_dataset_manager(actor, settings=settings)
    try:
        dataset = create_dataset(
            session,
            workspace_id=settings.workspace_id,
            actor_user_id=actor.user_id,
            request=request_body,
        )
    except DatasetResourceNotFoundError as exc:
        raise _dataset_http_error(
            status.HTTP_404_NOT_FOUND,
            "dataset_resource_not_found",
            str(exc),
            "Choose an available semantic model",
        ) from exc
    except DatasetConfigurationError as exc:
        raise _dataset_http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_dataset_configuration",
            str(exc),
            "Correct the dataset fields and try again",
        ) from exc
    return _dataset_detail_response(dataset)


@router.post(
    "/{dataset_id}/versions",
    response_model=DatasetDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_version_endpoint(
    dataset_id: UUID,
    request_body: CreateDatasetVersion,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> DatasetDetailResponse:
    _require_dataset_manager(actor, settings=settings)
    try:
        dataset = create_dataset_version(
            session,
            workspace_id=settings.workspace_id,
            actor_user_id=actor.user_id,
            dataset_id=dataset_id,
            request=request_body,
        )
    except DatasetResourceNotFoundError as exc:
        raise _dataset_http_error(
            status.HTTP_404_NOT_FOUND,
            "dataset_not_found",
            str(exc),
            "Refresh the dataset list",
        ) from exc
    except DatasetConfigurationError as exc:
        raise _dataset_http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_dataset_configuration",
            str(exc),
            "Correct the dataset fields and try again",
        ) from exc
    return _dataset_detail_response(dataset)


@router.get("", response_model=DatasetPageResponse)
def list_datasets_endpoint(
    session: DatabaseSession,
    settings: ApplicationSettings,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DatasetPageResponse:
    page = list_datasets(
        session,
        workspace_id=settings.workspace_id,
        offset=offset,
        limit=limit,
    )
    return DatasetPageResponse(
        items=[DatasetSummaryResponse.model_validate(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.get("/{dataset_id}", response_model=DatasetDetailResponse)
def read_dataset_endpoint(
    dataset_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> DatasetDetailResponse:
    dataset = get_dataset_detail(
        session,
        workspace_id=settings.workspace_id,
        dataset_id=dataset_id,
    )
    if dataset is None:
        raise _dataset_http_error(
            status.HTTP_404_NOT_FOUND,
            "dataset_not_found",
            "Dataset was not found",
            "Refresh the dataset list",
        )
    return _dataset_detail_response(dataset)


def _dataset_detail_response(dataset: DatasetDetail) -> DatasetDetailResponse:
    return DatasetDetailResponse.model_validate(dataset)


def _require_dataset_manager(actor: QueryPrincipal, *, settings: Settings) -> None:
    if actor.workspace_id != settings.workspace_id or not actor.has_permission("datasets:manage"):
        raise _dataset_http_error(
            status.HTTP_403_FORBIDDEN,
            "dataset_manage_forbidden",
            "Dataset management permission is required",
            "Ask a workspace administrator for dataset management access",
        )


def _dataset_http_error(
    status_code: int,
    code: str,
    message: str,
    action: str,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "action": action},
    )
