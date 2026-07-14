from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(url: str) -> Engine:
    dialect = make_url(url).get_backend_name()

    if dialect == "sqlite":
        engine = create_engine(url, connect_args={"check_same_thread": False})

        def enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        event.listen(engine, "connect", enable_foreign_keys)
        return engine

    if dialect == "postgresql":
        return create_engine(url, pool_pre_ping=True)

    msg = f"Unsupported database dialect: {dialect}"
    raise ValueError(msg)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
