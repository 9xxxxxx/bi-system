from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from bi_system.api.dependencies import CurrentActor, get_database_session
from bi_system.db.models import Role, User

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_database_session)]


class IdentityUserResponse(BaseModel):
    id: UUID
    username: str
    display_name: str


class IdentityRoleResponse(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None


@router.get("/users", response_model=list[IdentityUserResponse])
def list_identity_users(
    session: DatabaseSession,
    actor: CurrentActor,
) -> list[IdentityUserResponse]:
    _require_identity_manager(actor)
    users = session.scalars(
        select(User)
        .where(User.workspace_id == actor.workspace_id, User.status == "active")
        .order_by(User.display_name, User.username, User.id),
    ).all()
    return [IdentityUserResponse.model_validate(user, from_attributes=True) for user in users]


@router.get("/roles", response_model=list[IdentityRoleResponse])
def list_identity_roles(
    session: DatabaseSession,
    actor: CurrentActor,
) -> list[IdentityRoleResponse]:
    _require_identity_manager(actor)
    roles = session.scalars(
        select(Role)
        .where(Role.workspace_id == actor.workspace_id, Role.status == "active")
        .order_by(Role.name, Role.code, Role.id),
    ).all()
    return [IdentityRoleResponse.model_validate(role, from_attributes=True) for role in roles]


def _require_identity_manager(actor: CurrentActor) -> None:
    if not actor.has_permission("datasets:manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "identity_directory_forbidden",
                "message": "Dataset management permission is required",
                "action": "Ask a workspace administrator for dataset management access",
            },
        )
