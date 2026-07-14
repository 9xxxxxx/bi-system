from bi_system.db.session import create_database_engine, create_session_factory
from sqlalchemy import text


def test_sqlite_engine_executes_queries_and_enables_foreign_keys() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")

    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    finally:
        engine.dispose()


def test_session_factory_uses_engine_without_expiring_instances() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")

    try:
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()
