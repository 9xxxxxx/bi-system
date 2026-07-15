from collections.abc import Generator
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from bi_system.identity import QueryPrincipal
from bi_system.ingestion.storage import LocalContentAddressedStorage


def get_database_session(request: Request) -> Generator[Session]:
    session_factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with session_factory() as session:
        yield session


def get_file_storage(request: Request) -> LocalContentAddressedStorage:
    return cast(LocalContentAddressedStorage, request.app.state.file_storage)


def get_query_principal(request: Request) -> QueryPrincipal:
    principal = getattr(request.state, "query_principal", None)
    if not isinstance(principal, QueryPrincipal):
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
