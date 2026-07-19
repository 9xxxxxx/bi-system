import hashlib
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from bi_system.db.session import create_session_factory
from sqlalchemy.engine import Engine, make_url

from scripts import benchmark_m2_queries as benchmark
from spikes.m3.quality import fixture_tool


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


def test_benchmark_fixture_records_trusted_generator_provenance(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    fixture_tool.generate_benchmark(fixture_dir, 15)

    fixture = benchmark.validate_benchmark_fixture(fixture_dir, expected_rows=15)

    assert fixture.fixture_version == "m3-star-v2"
    assert fixture.fact_row_count == 15
    assert (
        fixture.trusted_source_manifest_sha256
        == hashlib.sha256(benchmark.TRUSTED_FIXTURE_MANIFEST.read_bytes()).hexdigest()
    )
    assert fixture.generator_contract == benchmark.BENCHMARK_GENERATOR_CONTRACT


def test_benchmark_fixture_rejects_resigned_dimension_tampering(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    fixture_tool.generate_benchmark(fixture_dir, 15)
    dimension_path = fixture_dir / "dim_product.csv"
    dimension_path.write_text(
        dimension_path.read_text(encoding="utf-8").replace("Widget Alpha", "Widget Omega", 1),
        encoding="utf-8",
        newline="",
    )
    _resign_benchmark_file(fixture_dir, "dim_product.csv")

    with pytest.raises(ValueError, match="does not match the trusted fixture"):
        benchmark.validate_benchmark_fixture(fixture_dir, expected_rows=15)


@pytest.mark.parametrize(
    ("needle", "replacement", "changed_field"),
    [
        ("1,B000001-O-001", "9,B000001-O-001", "sales_id"),
        ("B000001-O-001", "B000001-X-001", "order_id"),
        ("200.00", "201.00", "gross_amount"),
    ],
)
def test_benchmark_fixture_rejects_resigned_scaled_row_tampering(
    tmp_path: Path,
    needle: str,
    replacement: str,
    changed_field: str,
) -> None:
    fixture_dir = tmp_path / "fixture"
    fixture_tool.generate_benchmark(fixture_dir, 15)
    fact_path = fixture_dir / "fact_sales.csv"
    fact_path.write_text(
        fact_path.read_text(encoding="utf-8").replace(needle, replacement, 1),
        encoding="utf-8",
        newline="",
    )
    _resign_benchmark_file(fixture_dir, "fact_sales.csv")

    with pytest.raises(
        ValueError,
        match=rf"deterministic scaling contract: {changed_field}",
    ):
        benchmark.validate_benchmark_fixture(fixture_dir, expected_rows=15)


@pytest.mark.parametrize(
    ("row_count", "expected_batch_sizes"),
    [
        (5_000, [5_000]),
        (5_001, [5_000, 1]),
        (100_000, [5_000] * 20),
    ],
)
def test_fixture_insert_batches_are_bounded_and_lazy(
    row_count: int,
    expected_batch_sizes: list[int],
) -> None:
    consumed = 0

    def rows() -> Generator[dict[str, str]]:
        nonlocal consumed
        for index in range(row_count):
            consumed += 1
            yield {"value": str(index)}

    batches = benchmark._fixture_insert_batches(  # pyright: ignore[reportPrivateUsage]
        rows(),
        definitions=(
            benchmark.FixtureColumnSpec(name="value", data_type="integer", nullable=False),
        ),
        batch_id=uuid4(),
    )
    first = next(batches)

    assert consumed == min(row_count, benchmark.FIXTURE_INSERT_BATCH_SIZE)
    assert [len(first), *(len(batch) for batch in batches)] == expected_batch_sizes
    assert consumed == row_count


def test_fixture_seed_and_query_smoke_at_one_thousand_rows(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    database_dir = tmp_path / "database"
    fixture_tool.generate_benchmark(fixture_dir, 1_000)
    database_dir.mkdir()

    with benchmark.benchmark_database_engine(
        None,
        temporary_directory=database_dir,
        pool_capacity=2,
    ) as engine:
        session_factory = create_session_factory(engine)
        principal, request = benchmark.seed_benchmark(
            engine,
            session_factory,
            rows=1_000,
            fixture_dir=fixture_dir,
        )
        duration_ms = benchmark.run_once(
            session_factory,
            principal=principal,
            request=request,
            timeout_seconds=10,
        )

    assert duration_ms > 0


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


def _resign_benchmark_file(fixture_dir: Path, filename: str) -> None:
    path = fixture_dir / filename
    content = path.read_bytes()
    manifest_path = fixture_dir / "benchmark_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][filename] = {
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
