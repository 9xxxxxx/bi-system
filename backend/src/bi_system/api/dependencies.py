from collections.abc import Generator
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from bi_system.core.config import Settings, get_settings
from bi_system.identity import QueryPrincipal, resolve_query_principal
from bi_system.ingestion.storage import LocalContentAddressedStorage

SESSION_COOKIE_NAME = "bi_session"


def get_database_session(request: Request) -> Generator[Session]:
    session_factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with session_factory() as session:
        yield session


def get_file_storage(request: Request) -> LocalContentAddressedStorage:
    return cast(LocalContentAddressedStorage, request.app.state.file_storage)


def get_query_principal(
    request: Request,
    session: Annotated[Session, Depends(get_database_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> QueryPrincipal:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    principal = (
        resolve_query_principal(
            session,
            workspace_id=settings.workspace_id,
            token=token,
        )
        if token
        else None
    )
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "authentication_required",
                "message": "Authentication is required",
                "action": "Sign in and try again",
            },
        )
    return principal


CurrentActor = Annotated[QueryPrincipal, Depends(get_query_principal)]
