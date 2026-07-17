import pytest
from bi_system.core.config import get_settings
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.modeling.query_timeout import dataset_query_deadline, is_query_timeout_error
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_postgres_statement_timeout_is_transaction_local_and_cancellable() -> None:
    engine = create_database_engine(get_settings().database_url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.skip("PostgreSQL-only timeout verification")
    session_factory = create_session_factory(engine)
    try:
        with (
            session_factory() as session,
            pytest.raises(DBAPIError) as captured,
            dataset_query_deadline(session, timeout_seconds=0.05),
        ):
            session.execute(text("SELECT pg_sleep(1)"))
        assert is_query_timeout_error(captured.value)

        with session_factory() as session:
            assert session.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()
