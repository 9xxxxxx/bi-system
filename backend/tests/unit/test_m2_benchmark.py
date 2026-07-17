from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import Engine, make_url

from scripts import benchmark_m2_queries as benchmark


def test_parse_args_defaults_to_temporary_sqlite() -> None:
    args = benchmark.parse_args([])

    assert args.database_url is None
    assert args.rows == 100_000


def test_parse_args_accepts_postgresql_database_url() -> None:
    args = benchmark.parse_args(
        ["--database-url", "postgresql+psycopg://bi_system@localhost/benchmark"]
    )

    assert args.database_url == "postgresql+psycopg://bi_system@localhost/benchmark"


def test_parse_args_rejects_non_postgresql_database_url() -> None:
    with pytest.raises(SystemExit, match="2"):
        benchmark.parse_args(["--database-url", "sqlite+pysqlite:///benchmark.db"])


def test_temporary_sqlite_engine_is_disposed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = MagicMock(spec=Engine)
    engine_factory = MagicMock(return_value=engine)
    monkeypatch.setattr(benchmark, "create_benchmark_engine", engine_factory)

    with benchmark.benchmark_database_engine(None, temporary_directory=tmp_path) as result:
        assert result is engine

    engine_factory.assert_called_once_with(
        f"sqlite+pysqlite:///{(tmp_path / 'benchmark.db').as_posix()}",
        pool_capacity=5,
    )
    engine.dispose.assert_called_once_with()


def test_postgresql_schema_is_removed_after_benchmark_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administration_engine = MagicMock(spec=Engine)
    benchmark_engine = MagicMock(spec=Engine)
    connection = administration_engine.begin.return_value.__enter__.return_value
    administration_engine_factory = MagicMock(return_value=administration_engine)
    benchmark_engine_factory = MagicMock(return_value=benchmark_engine)
    monkeypatch.setattr(benchmark, "create_database_engine", administration_engine_factory)
    monkeypatch.setattr(benchmark, "create_benchmark_engine", benchmark_engine_factory)

    with (
        pytest.raises(RuntimeError, match="benchmark failed"),
        benchmark.benchmark_database_engine(
            "postgresql+psycopg://bi_system:secret@localhost/benchmark?sslmode=require",
            temporary_directory=tmp_path,
        ),
    ):
        raise RuntimeError("benchmark failed")

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements[0].startswith("CREATE SCHEMA bi_m2_benchmark_")
    assert statements[1].startswith("DROP SCHEMA IF EXISTS bi_m2_benchmark_")
    assert statements[1].endswith(" CASCADE")
    administration_engine_factory.assert_called_once_with(
        "postgresql+psycopg://bi_system:secret@localhost/benchmark?sslmode=require"
    )
    benchmark_url = make_url(benchmark_engine_factory.call_args.args[0])
    assert benchmark_url.password == "secret"
    assert benchmark_url.query["sslmode"] == "require"
    options = benchmark_url.query["options"]
    assert isinstance(options, str)
    assert options.startswith("-csearch_path=bi_m2_benchmark_")
    assert benchmark_engine_factory.call_args.kwargs == {"pool_capacity": 5}
    benchmark_engine.dispose.assert_called_once_with()
    administration_engine.dispose.assert_called_once_with()


def test_main_reports_database_dialect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = benchmark.create_database_engine("sqlite+pysqlite:///:memory:")
    session_factory = MagicMock()
    principal = MagicMock()
    request = MagicMock()
    monkeypatch.setattr(
        benchmark,
        "parse_args",
        MagicMock(
            return_value=MagicMock(
                database_url=None,
                rows=1,
                concurrency=1,
                iterations=1,
                timeout_seconds=1,
            )
        ),
    )
    monkeypatch.setattr(
        benchmark,
        "benchmark_database_engine",
        _engine_context_factory(engine),
    )
    monkeypatch.setattr(
        benchmark,
        "create_session_factory",
        MagicMock(return_value=session_factory),
    )
    monkeypatch.setattr(benchmark, "seed_benchmark", MagicMock(return_value=(principal, request)))
    monkeypatch.setattr(benchmark, "run_once", MagicMock(return_value=1.0))
    monkeypatch.setattr(benchmark, "run_benchmark", MagicMock(return_value=([2.0], {}, 0.5)))

    assert benchmark.main() == 0
    assert '"dialect": "sqlite"' in capsys.readouterr().out


class _engine_context:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def __enter__(self) -> Engine:
        return self.engine

    def __exit__(self, *_args: Any) -> None:
        self.engine.dispose()
        return None


def _engine_context_factory(engine: Engine) -> Any:
    def create_context(
        _database_url: str | None,
        *,
        temporary_directory: Path,
        pool_capacity: int,
    ) -> _engine_context:
        del temporary_directory
        del pool_capacity
        return _engine_context(engine)

    return create_context
