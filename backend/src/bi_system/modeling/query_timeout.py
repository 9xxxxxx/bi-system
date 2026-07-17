from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from time import monotonic
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


@contextmanager
def dataset_query_deadline(
    session: Session,
    *,
    timeout_seconds: float,
) -> Generator[None]:
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        timeout_ms = max(1, int(timeout_seconds * 1_000))
        session.execute(
            text("SELECT set_config('statement_timeout', :timeout_value, true)"),
            {"timeout_value": f"{timeout_ms}ms"},
        )
        yield
        return
    if dialect_name != "sqlite":
        yield
        return

    dbapi_connection = _sqlite_dbapi_connection(session)
    deadline = monotonic() + timeout_seconds
    dbapi_connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1_000)
    try:
        yield
    finally:
        dbapi_connection.set_progress_handler(None, 0)


def is_query_timeout_error(exc: DBAPIError) -> bool:
    original = exc.orig
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate == "57014":
        return True
    return isinstance(original, sqlite3.OperationalError) and "interrupted" in str(original).lower()


def _sqlite_dbapi_connection(session: Session) -> sqlite3.Connection:
    pooled_connection = session.connection().connection
    driver_connection = getattr(pooled_connection, "driver_connection", pooled_connection)
    return cast(sqlite3.Connection, cast(Any, driver_connection))
