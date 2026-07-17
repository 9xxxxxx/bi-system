from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from bi_system.api.dependencies import CurrentActor, get_database_session
from bi_system.core.config import Settings, get_settings
from bi_system.identity import QueryPrincipal
from bi_system.modeling.expression import FilterExpression
from bi_system.modeling.row_policies import (
    RowPolicyConfigurationError,
    RowPolicyConflictError,
    RowPolicyDetail,
    RowPolicyLifecycleError,
    RowPolicyResourceNotFoundError,
    activate_row_policy,
    create_row_policy,
    create_row_policy_version,
    get_row_policy,
    list_row_policies,
    replace_row_policy_bindings,
)
from bi_system.modeling.row_policy_contracts import (
    CreateRowPolicy,
    CreateRowPolicyVersion,
    ReplaceRowPolicyBindings,
)

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class RowPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    series_id: UUID
    dataset_id: UUID
    name: str
    version: int
    effect: Literal["allow", "deny"]
    expression: FilterExpression
    status: Literal["draft", "active", "disabled"]
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    user_ids: list[UUID]
    role_ids: list[UUID]


class RowPolicyPageResponse(BaseModel):
    items: list[RowPolicyResponse]
    total: int
    offset: int
    limit: int


@router.post("", response_model=RowPolicyResponse, status_code=status.HTTP_201_CREATED)
def create_row_policy_endpoint(
    request_body: CreateRowPolicy,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> RowPolicyResponse:
    _require_row_policy_manager(actor, settings=settings)
    try:
        policy = create_row_policy(
            session,
            workspace_id=settings.workspace_id,
            actor_user_id=actor.user_id,
            request=request_body,
        )
    except RowPolicyResourceNotFoundError as exc:
        raise _row_policy_http_error(404, "row_policy_resource_not_found", str(exc)) from exc
    except RowPolicyConfigurationError as exc:
        raise _row_policy_http_error(422, "invalid_row_policy_configuration", str(exc)) from exc
    except RowPolicyConflictError as exc:
        raise _row_policy_http_error(409, "row_policy_version_conflict", str(exc)) from exc
    return _row_policy_response(policy)


@router.get("", response_model=RowPolicyPageResponse)
def list_row_policies_endpoint(
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
    dataset_id: UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RowPolicyPageResponse:
    _require_row_policy_manager(actor, settings=settings)
    page = list_row_policies(
        session,
        workspace_id=settings.workspace_id,
        dataset_id=dataset_id,
        offset=offset,
        limit=limit,
    )
    return RowPolicyPageResponse(
        items=[_row_policy_response(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.post(
    "/{row_policy_id}/versions",
    response_model=RowPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_row_policy_version_endpoint(
    row_policy_id: UUID,
    request_body: CreateRowPolicyVersion,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> RowPolicyResponse:
    _require_row_policy_manager(actor, settings=settings)
    try:
        policy = create_row_policy_version(
            session,
            workspace_id=settings.workspace_id,
            actor_user_id=actor.user_id,
            row_policy_id=row_policy_id,
            request=request_body,
        )
    except RowPolicyResourceNotFoundError as exc:
        raise _row_policy_http_error(404, "row_policy_not_found", str(exc)) from exc
    except RowPolicyConfigurationError as exc:
        raise _row_policy_http_error(422, "invalid_row_policy_configuration", str(exc)) from exc
    except RowPolicyConflictError as exc:
        raise _row_policy_http_error(409, "row_policy_version_conflict", str(exc)) from exc
    return _row_policy_response(policy)


@router.put("/{row_policy_id}/bindings", response_model=RowPolicyResponse)
def replace_row_policy_bindings_endpoint(
    row_policy_id: UUID,
    request_body: ReplaceRowPolicyBindings,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> RowPolicyResponse:
    _require_row_policy_manager(actor, settings=settings)
    try:
        policy = replace_row_policy_bindings(
            session,
            workspace_id=settings.workspace_id,
            row_policy_id=row_policy_id,
            request=request_body,
        )
    except RowPolicyResourceNotFoundError as exc:
        raise _row_policy_http_error(
            404, "row_policy_binding_resource_not_found", str(exc)
        ) from exc
    except RowPolicyLifecycleError as exc:
        raise _row_policy_http_error(409, "row_policy_binding_conflict", str(exc)) from exc
    return _row_policy_response(policy)


@router.post("/{row_policy_id}/activate", response_model=RowPolicyResponse)
def activate_row_policy_endpoint(
    row_policy_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> RowPolicyResponse:
    _require_row_policy_manager(actor, settings=settings)
    try:
        policy = activate_row_policy(
            session,
            workspace_id=settings.workspace_id,
            row_policy_id=row_policy_id,
        )
    except RowPolicyResourceNotFoundError as exc:
        raise _row_policy_http_error(404, "row_policy_not_found", str(exc)) from exc
    except RowPolicyConfigurationError as exc:
        raise _row_policy_http_error(422, "invalid_row_policy_configuration", str(exc)) from exc
    except RowPolicyLifecycleError as exc:
        raise _row_policy_http_error(409, "row_policy_activation_conflict", str(exc)) from exc
    return _row_policy_response(policy)


@router.get("/{row_policy_id}", response_model=RowPolicyResponse)
def read_row_policy_endpoint(
    row_policy_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
    actor: CurrentActor,
) -> RowPolicyResponse:
    _require_row_policy_manager(actor, settings=settings)
    policy = get_row_policy(
        session,
        workspace_id=settings.workspace_id,
        row_policy_id=row_policy_id,
    )
    if policy is None:
        raise _row_policy_http_error(404, "row_policy_not_found", "Row policy was not found")
    return _row_policy_response(policy)


def _row_policy_response(policy: RowPolicyDetail) -> RowPolicyResponse:
    return RowPolicyResponse.model_validate(policy)


def _require_row_policy_manager(actor: QueryPrincipal, *, settings: Settings) -> None:
    if actor.workspace_id != settings.workspace_id or not actor.has_permission("datasets:manage"):
        raise _row_policy_http_error(
            status.HTTP_403_FORBIDDEN,
            "row_policy_manage_forbidden",
            "Dataset management permission is required",
        )


def _row_policy_http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "action": "Correct the row policy configuration and try again",
        },
    )
