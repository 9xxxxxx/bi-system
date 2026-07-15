from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bi_system.api.dependencies import get_database_session
from bi_system.core.config import Settings, get_settings
from bi_system.ingestion.data_sources import (
    DataSourceCatalogEntry,
    get_data_source_schema,
    list_data_sources,
)

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class DataSourceResponse(BaseModel):
    id: UUID
    name: str
    status: str
    latest_active_batch_id: UUID | None
    active_row_count: int


class DataSourceFieldResponse(BaseModel):
    id: UUID
    display_name: str
    data_type: str
    nullable: bool


class DataSourceSchemaResponse(DataSourceResponse):
    fields: list[DataSourceFieldResponse]


@router.get("", response_model=list[DataSourceSchemaResponse])
def list_data_sources_endpoint(
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> list[DataSourceSchemaResponse]:
    return [
        _data_source_schema_response(source)
        for source in list_data_sources(session, workspace_id=settings.workspace_id)
    ]


@router.get("/{data_source_id}/schema", response_model=DataSourceSchemaResponse)
def read_data_source_schema_endpoint(
    data_source_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> DataSourceSchemaResponse:
    source = get_data_source_schema(
        session,
        workspace_id=settings.workspace_id,
        data_source_id=data_source_id,
    )
    if source is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "data_source_not_found",
                "message": "Data source was not found",
                "action": "Choose an available data source",
            },
        )
    return _data_source_schema_response(source)


def _data_source_schema_response(source: DataSourceCatalogEntry) -> DataSourceSchemaResponse:
    return DataSourceSchemaResponse(
        **_data_source_response(source).model_dump(),
        fields=[
            DataSourceFieldResponse(
                id=field.id,
                display_name=field.display_name,
                data_type=field.data_type,
                nullable=field.nullable,
            )
            for field in source.fields
        ],
    )


def _data_source_response(source: DataSourceCatalogEntry) -> DataSourceResponse:
    return DataSourceResponse(
        id=source.id,
        name=source.name,
        status=source.status,
        latest_active_batch_id=source.latest_active_batch_id,
        active_row_count=source.active_row_count,
    )
