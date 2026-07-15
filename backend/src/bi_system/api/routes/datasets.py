from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from bi_system.api.dependencies import get_database_session
from bi_system.core.config import Settings, get_settings
from bi_system.modeling.datasets import get_dataset_summary, list_datasets

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


@router.get("/{dataset_id}", response_model=DatasetSummaryResponse)
def read_dataset_endpoint(
    dataset_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> DatasetSummaryResponse:
    dataset = get_dataset_summary(
        session,
        workspace_id=settings.workspace_id,
        dataset_id=dataset_id,
    )
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "dataset_not_found",
                "message": "Dataset was not found",
                "action": "Refresh the dataset list",
            },
        )
    return DatasetSummaryResponse.model_validate(dataset)
