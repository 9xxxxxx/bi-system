import json
from pathlib import Path
from time import sleep
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from scripts import benchmark_m3_chart_queries as benchmark


def test_parse_args_defaults_to_five_warmups() -> None:
    assert benchmark.parse_args([]).warmups == 5


def test_parse_args_accepts_explicit_warmups() -> None:
    assert benchmark.parse_args(["--warmups", "2"]).warmups == 2


def test_parse_args_rejects_non_positive_warmups() -> None:
    with pytest.raises(SystemExit, match="2"):
        benchmark.parse_args(["--warmups", "0"])


def test_run_benchmark_returns_stable_indexes_with_error_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def delayed_run_once(
        _session_factory: Any,
        *,
        context: benchmark.BenchmarkContext,
        timeout_seconds: int,
        sample_index: int = -1,
    ) -> benchmark.BenchmarkSample:
        del context, timeout_seconds
        sleep((3 - sample_index) * 0.01)
        if sample_index == 1:
            raise RuntimeError("measured request failed")
        return benchmark.BenchmarkSample(
            sample_index=sample_index,
            duration_ms=float(sample_index),
            truncated_results=sample_index % 2,
        )

    monkeypatch.setattr(benchmark, "run_once", delayed_run_once)

    samples, errors, timeouts, _wall_seconds = benchmark.run_benchmark(
        MagicMock(),
        context=MagicMock(),
        concurrency=4,
        iterations=1,
        timeout_seconds=1,
    )

    assert [sample.sample_index for sample in samples] == [0, 2, 3]
    assert errors == {"RuntimeError": 1}
    assert timeouts == 0


def test_build_output_includes_aggregate_and_raw_evidence() -> None:
    samples = [
        benchmark.BenchmarkSample(sample_index=0, duration_ms=2.25, truncated_results=0),
        benchmark.BenchmarkSample(sample_index=2, duration_ms=7.75, truncated_results=1),
    ]
    environment: dict[str, object] = {
        "dialect": "sqlite",
        "server_version": "3.49.1",
    }

    output = benchmark.build_output(
        dialect="sqlite",
        rows=100,
        concurrency=2,
        iterations=2,
        warmups=5,
        warmups_completed=5,
        queries_per_request=3,
        samples=samples,
        errors={"failure": 2},
        timeouts=1,
        wall_seconds=0.5,
        environment=environment,
    )

    assert output["requests"] == 4
    assert output["completed"] == 2
    assert output["error_count"] == 2
    assert output["p50_ms"] == 2.25
    assert output["p95_ms"] == 7.75
    assert output["max_ms"] == 7.75
    assert output["cache_state"] == "warm"
    assert output["percentile_method"] == "nearest-rank"
    assert output["environment"] == environment
    assert output["samples"] == [
        {"sample_index": 0, "duration_ms": 2.25, "truncated_results": 0},
        {"sample_index": 2, "duration_ms": 7.75, "truncated_results": 1},
    ]


def test_environment_metadata_reports_runtime_and_database() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    engine.dialect.server_version_info = (3, 49, 1)
    try:
        metadata = benchmark.environment_metadata(engine)
    finally:
        engine.dispose()

    assert metadata["python_version"]
    assert metadata["python_implementation"]
    assert metadata["platform"]
    assert "machine" in metadata
    assert "processor" in metadata
    assert metadata["cpu_count"]
    assert metadata["dialect"] == "sqlite"
    assert metadata["server_version"] == "3.49.1"


def test_main_runs_warmups_and_writes_same_json_as_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "evidence" / "benchmark.json"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    engine.dialect.server_version_info = (3, 49, 1)
    session_factory = MagicMock()
    principal = MagicMock()
    dataset_request = MagicMock()
    context = MagicMock(requests=(MagicMock(), MagicMock(), MagicMock()))
    run_once = MagicMock(
        return_value=benchmark.BenchmarkSample(
            sample_index=-1,
            duration_ms=1.0,
            truncated_results=0,
        )
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
    monkeypatch.setattr(
        benchmark,
        "seed_benchmark",
        MagicMock(return_value=(principal, dataset_request)),
    )
    monkeypatch.setattr(
        benchmark,
        "seed_dashboard_benchmark",
        MagicMock(return_value=context),
    )
    monkeypatch.setattr(benchmark, "run_once", run_once)
    monkeypatch.setattr(
        benchmark,
        "run_benchmark",
        MagicMock(
            return_value=(
                [
                    benchmark.BenchmarkSample(
                        sample_index=0,
                        duration_ms=3.5,
                        truncated_results=0,
                    )
                ],
                {},
                0,
                0.25,
            )
        ),
    )

    result = benchmark.main(
        [
            "--rows",
            "1",
            "--concurrency",
            "1",
            "--iterations",
            "1",
            "--output",
            str(output_path),
        ]
    )

    stdout_json = json.loads(capsys.readouterr().out)
    file_json = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert run_once.call_count == 5
    assert stdout_json == file_json
    assert stdout_json["warmups"] == 5
    assert stdout_json["warmups_completed"] == 5


class _engine_context:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def __enter__(self) -> Engine:
        return self.engine

    def __exit__(self, *_args: object) -> None:
        self.engine.dispose()


def _engine_context_factory(engine: Engine) -> Any:
    def create_context(
        _database_url: str | None,
        *,
        temporary_directory: Path,
        pool_capacity: int,
    ) -> _engine_context:
        del temporary_directory, pool_capacity
        return _engine_context(engine)

    return create_context
