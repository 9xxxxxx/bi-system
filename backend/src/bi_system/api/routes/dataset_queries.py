from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bi_system.api.dependencies import CurrentActor, get_database_session
from bi_system.modeling.contracts import DatasetQueryRequest
from bi_system.modeling.query_service import (
    DatasetQueryError,
    DatasetQueryForbiddenError,
    DatasetQueryNotFoundError,
    execute_dataset_query,
    validate_dataset_query,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_database_session)]


class DatasetQueryValidationResponse(BaseModel):
    valid: bool
    columns: list[str]
    dataset_version: int


class DatasetQueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
    elapsed_ms: float
    dataset_version: int
    source_batch_ids: list[UUID]


@router.post("/validate", response_model=DatasetQueryValidationResponse)
def validate_dataset_query_endpoint(
    request_body: DatasetQueryRequest,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DatasetQueryValidationResponse:
    try:
        prepared = validate_dataset_query(session, principal=actor, request=request_body)
    except DatasetQueryError as exc:
        raise _dataset_query_http_error(exc) from exc
    return DatasetQueryValidationResponse(
        valid=True,
        columns=list(prepared.compiled.output_names),
        dataset_version=prepared.dataset.version,
    )


@router.post("", response_model=DatasetQueryResponse)
def execute_dataset_query_endpoint(
    request_body: DatasetQueryRequest,
    session: DatabaseSession,
    actor: CurrentActor,
) -> DatasetQueryResponse:
    try:
        result = execute_dataset_query(session, principal=actor, request=request_body)
    except DatasetQueryError as exc:
        raise _dataset_query_http_error(exc) from exc
    return DatasetQueryResponse(
        columns=list(result.columns),
        rows=list(result.rows),
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
        dataset_version=result.dataset_version,
        source_batch_ids=list(result.source_batch_ids),
    )


def _dataset_query_http_error(exc: DatasetQueryError) -> HTTPException:
    if isinstance(exc, DatasetQueryNotFoundError):
        status_code = 404
    elif isinstance(exc, DatasetQueryForbiddenError):
        status_code = 403
    else:
        status_code = 422
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc), "action": exc.action},
    )
