from collections.abc import Generator
from typing import cast

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from bi_system.ingestion.storage import LocalContentAddressedStorage


def get_database_session(request: Request) -> Generator[Session]:
    session_factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with session_factory() as session:
        yield session


def get_file_storage(request: Request) -> LocalContentAddressedStorage:
    return cast(LocalContentAddressedStorage, request.app.state.file_storage)
