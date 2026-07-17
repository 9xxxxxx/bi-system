# pyright: reportPrivateUsage=false
from typing import cast

import pytest
from bi_system.api.routes.dataset_queries import _dataset_query_http_error
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.modeling.query_service import DatasetQueryTimeoutError
from bi_system.modeling.query_timeout import dataset_query_deadline, is_query_timeout_error
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_sqlite_deadline_interrupts_and_cleans_pooled_connection() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    session_factory = create_session_factory(engine)
    recursive_query = text(
        "WITH RECURSIVE counter(value) AS ("
        "VALUES(0) UNION ALL SELECT value + 1 FROM counter WHERE value < 100000000"
        ") SELECT sum(value) FROM counter"
    )

    try:
        with (
            session_factory() as session,
            pytest.raises(DBAPIError) as captured,
            dataset_query_deadline(session, timeout_seconds=0.001),
        ):
            session.execute(recursive_query).scalar_one()
        assert is_query_timeout_error(captured.value)

        with session_factory() as session:
            assert session.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()


def test_timeout_error_maps_to_structured_gateway_timeout() -> None:
    error = DatasetQueryTimeoutError(
        "dataset_query_timeout",
        "Dataset query exceeded its execution deadline",
        "Reduce the query scope",
    )

    response = _dataset_query_http_error(error)

    assert response.status_code == 504
    assert cast(dict[str, str], response.detail)["code"] == "dataset_query_timeout"
