import os
import tempfile
from pathlib import Path

import pytest
from bi_system.db.session import create_database_engine
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.benchmark_m2_queries import benchmark_database_engine


def test_postgres_benchmark_schema_is_isolated_and_removed() -> None:
    database_url = os.environ.get("BI_DATABASE_URL")
    if database_url is None:
        pytest.skip("BI_DATABASE_URL is required for PostgreSQL benchmark verification")

    administration_engine = create_database_engine(database_url)
    if administration_engine.dialect.name != "postgresql":
        administration_engine.dispose()
        pytest.skip("PostgreSQL-only benchmark verification")

    try:
        schemas_before = benchmark_schemas(administration_engine)
        with (
            tempfile.TemporaryDirectory(prefix="bi-m2-benchmark-test-") as directory,
            benchmark_database_engine(
                database_url,
                temporary_directory=Path(directory),
            ) as engine,
            engine.begin() as connection,
        ):
            schema_name = connection.scalar(text("SELECT current_schema()"))
            connection.execute(text("CREATE TABLE cleanup_marker (id integer)"))

            assert isinstance(schema_name, str)
            assert schema_name.startswith("bi_m2_benchmark_")

        assert benchmark_schemas(administration_engine) == schemas_before
    finally:
        administration_engine.dispose()


def benchmark_schemas(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.scalars(
                text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'bi_m2_benchmark_%'")
            )
        )
