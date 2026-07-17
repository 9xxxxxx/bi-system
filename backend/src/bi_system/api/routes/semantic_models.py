from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bi_system.api.dependencies import CurrentActor, get_database_session
from bi_system.modeling.model_contracts import CreateSemanticModel
from bi_system.modeling.semantic_models import (
    SemanticModelConflictError,
    SemanticModelNotFoundError,
    SemanticModelServiceError,
    StoredSemanticModel,
    activate_semantic_model,
    create_semantic_model,
    create_semantic_model_version,
    get_semantic_model,
    list_semantic_models,
    validate_semantic_model,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_database_session)]


class SemanticModelSummaryResponse(BaseModel):
    id: UUID
    series_id: UUID
    name: str
    version: int
    description: str | None
    status: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class SemanticModelSourceResponse(BaseModel):
    id: UUID
    target_id: UUID
    alias: str
    role: str
    ordinal: int


class SemanticModelJoinKeyResponse(BaseModel):
    left_column_id: UUID
    right_column_id: UUID
    ordinal: int


class SemanticModelJoinResponse(BaseModel):
    id: UUID
    left_source_id: UUID
    right_source_id: UUID
    join_type: str
    cardinality: str
    ordinal: int
    keys: list[SemanticModelJoinKeyResponse]


class SemanticModelResponse(SemanticModelSummaryResponse):
    sources: list[SemanticModelSourceResponse]
    joins: list[SemanticModelJoinResponse]


class SemanticModelValidationResponse(BaseModel):
    valid: bool
    series_id: UUID
    version: int
    source_count: int
    join_count: int
    warnings: list[str]


@router.post("/validate", response_model=SemanticModelValidationResponse)
def validate_semantic_model_endpoint(
    request_body: CreateSemanticModel,
    session: DatabaseSession,
    actor: CurrentActor,
) -> SemanticModelValidationResponse:
    _require_semantic_model_manager(actor)
    try:
        validated = validate_semantic_model(
            session,
            workspace_id=actor.workspace_id,
            actor_user_id=actor.user_id,
            request=request_body,
        )
    except SemanticModelServiceError as exc:
        raise _semantic_model_http_error(exc) from exc
    return SemanticModelValidationResponse(
        valid=True,
        series_id=validated.series_id,
        version=validated.version,
        source_count=len(request_body.sources),
        join_count=len(request_body.joins),
        warnings=[],
    )


@router.post("", response_model=SemanticModelResponse, status_code=status.HTTP_201_CREATED)
def create_semantic_model_endpoint(
    request_body: CreateSemanticModel,
    session: DatabaseSession,
    actor: CurrentActor,
) -> SemanticModelResponse:
    _require_semantic_model_manager(actor)
    try:
        stored = create_semantic_model(
            session,
            workspace_id=actor.workspace_id,
            actor_user_id=actor.user_id,
            request=request_body,
        )
    except SemanticModelServiceError as exc:
        raise _semantic_model_http_error(exc) from exc
    return _model_response(stored)


@router.post(
    "/{model_id}/versions",
    response_model=SemanticModelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_semantic_model_version_endpoint(
    model_id: UUID,
    request_body: CreateSemanticModel,
    session: DatabaseSession,
    actor: CurrentActor,
) -> SemanticModelResponse:
    _require_semantic_model_manager(actor)
    try:
        stored = create_semantic_model_version(
            session,
            workspace_id=actor.workspace_id,
            actor_user_id=actor.user_id,
            model_id=model_id,
            request=request_body,
        )
    except SemanticModelServiceError as exc:
        raise _semantic_model_http_error(exc) from exc
    return _model_response(stored)


@router.post("/{model_id}/activate", response_model=SemanticModelResponse)
def activate_semantic_model_endpoint(
    model_id: UUID,
    session: DatabaseSession,
    actor: CurrentActor,
) -> SemanticModelResponse:
    _require_semantic_model_manager(actor)
    try:
        stored = activate_semantic_model(
            session,
            workspace_id=actor.workspace_id,
            model_id=model_id,
        )
    except SemanticModelServiceError as exc:
        raise _semantic_model_http_error(exc) from exc
    return _model_response(stored)


@router.get("", response_model=list[SemanticModelSummaryResponse])
def list_semantic_models_endpoint(
    session: DatabaseSession,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SemanticModelSummaryResponse]:
    return [
        SemanticModelSummaryResponse.model_validate(model, from_attributes=True)
        for model in list_semantic_models(
            session,
            workspace_id=actor.workspace_id,
            limit=limit,
        )
    ]


@router.get("/{model_id}", response_model=SemanticModelResponse)
def read_semantic_model_endpoint(
    model_id: UUID,
    session: DatabaseSession,
    actor: CurrentActor,
) -> SemanticModelResponse:
    stored = get_semantic_model(
        session,
        workspace_id=actor.workspace_id,
        model_id=model_id,
    )
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "semantic_model_not_found",
                "message": "Semantic model was not found",
                "action": "Choose a model from the current workspace",
            },
        )
    return _model_response(stored)


def _model_response(stored: StoredSemanticModel) -> SemanticModelResponse:
    summary = SemanticModelSummaryResponse.model_validate(stored.model, from_attributes=True)
    return SemanticModelResponse(
        **summary.model_dump(),
        sources=[
            SemanticModelSourceResponse(
                id=source.id,
                target_id=source.target_id,
                alias=source.alias,
                role=source.source_role,
                ordinal=source.ordinal,
            )
            for source in stored.sources
        ],
        joins=[
            SemanticModelJoinResponse(
                id=stored_join.join.id,
                left_source_id=stored_join.join.left_source_id,
                right_source_id=stored_join.join.right_source_id,
                join_type=stored_join.join.join_type,
                cardinality=stored_join.join.cardinality,
                ordinal=stored_join.join.ordinal,
                keys=[
                    SemanticModelJoinKeyResponse(
                        left_column_id=key.left_column_id,
                        right_column_id=key.right_column_id,
                        ordinal=key.ordinal,
                    )
                    for key in stored_join.keys
                ],
            )
            for stored_join in stored.joins
        ],
    )


def _semantic_model_http_error(exc: SemanticModelServiceError) -> HTTPException:
    if isinstance(exc, SemanticModelNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, SemanticModelConflictError):
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc), "action": exc.action},
    )


def _require_semantic_model_manager(actor: CurrentActor) -> None:
    if not actor.has_permission("datasets:manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "semantic_model_manage_forbidden",
                "message": "Dataset management permission is required",
                "action": "Ask a workspace administrator for dataset management access",
            },
        )
