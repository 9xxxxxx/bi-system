from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from bi_system.api.dependencies import (
    SESSION_COOKIE_NAME,
    CurrentActor,
    get_database_session,
)
from bi_system.core.config import Settings, get_settings
from bi_system.db.models import User
from bi_system.identity import create_authenticated_session, revoke_session_token

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class CurrentUserResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    username: str
    display_name: str
    must_change_password: bool
    role_ids: list[UUID]
    permissions: list[str]
    is_system_admin: bool


@router.post("/login", response_model=CurrentUserResponse)
def login_endpoint(
    request_body: LoginRequest,
    response: Response,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> CurrentUserResponse:
    authenticated = create_authenticated_session(
        session,
        workspace_id=settings.workspace_id,
        username=request_body.username,
        password=request_body.password,
    )
    if authenticated is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_credentials",
                "message": "Username or password is incorrect",
                "action": "Check your credentials and try again",
            },
        )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=authenticated.token,
        expires=authenticated.expires_at,
        max_age=12 * 60 * 60,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )
    return _current_user_response(authenticated.user, actor=authenticated.principal)


@router.get("/me", response_model=CurrentUserResponse)
def current_user_endpoint(actor: CurrentActor, session: DatabaseSession) -> CurrentUserResponse:
    user = session.get(User, actor.user_id)
    if user is None or user.status != "active":
        raise _authentication_required()
    return _current_user_response(user, actor=actor)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_endpoint(request: Request, response: Response, session: DatabaseSession) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        revoke_session_token(session, token=token)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def _current_user_response(user: User, *, actor: CurrentActor) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        workspace_id=user.workspace_id,
        username=user.username,
        display_name=user.display_name,
        must_change_password=user.must_change_password,
        role_ids=sorted(actor.role_ids, key=str),
        permissions=sorted(actor.permissions),
        is_system_admin=actor.is_system_admin,
    )


def _authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "authentication_required",
            "message": "Authentication is required",
            "action": "Sign in and try again",
        },
    )
