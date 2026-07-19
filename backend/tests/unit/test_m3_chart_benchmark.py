import json
import subprocess
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from bi_system.dashboards.chart_query import ChartColumn, DashboardChartResult
from bi_system.dashboards.filters import ResolvedFilterEvidence
from bi_system.db.session import create_session_factory
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from scripts import benchmark_m3_chart_queries as benchmark
from scripts.benchmark_m2_queries import (
    benchmark_database_engine,
    seed_benchmark,
    validate_benchmark_fixture,
)
from spikes.m3.quality import fixture_tool


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
        round_index: int = -1,
        worker_index: int = -1,
        sample_index: int = -1,
        start_barrier: Any = None,
    ) -> benchmark.BenchmarkSample:
        del context, timeout_seconds
        if start_barrier is not None:
            start_barrier.wait()
        sleep((3 - sample_index) * 0.01)
        if sample_index == 1:
            raise RuntimeError("measured request failed")
        return benchmark.BenchmarkSample(
            sample_index=sample_index,
            duration_ms=float(sample_index),
            truncated_results=sample_index % 2,
            results=(),
            round_index=round_index,
            worker_index=worker_index,
        )

    monkeypatch.setattr(benchmark, "run_once", delayed_run_once)

    samples, failures, errors, timeouts, _wall_seconds = benchmark.run_benchmark(
        MagicMock(),
        context=MagicMock(),
        concurrency=4,
        iterations=1,
        timeout_seconds=1,
    )

    assert [sample.sample_index for sample in samples] == [0, 2, 3]
    assert [
        (failure.round_index, failure.worker_index, failure.sample_index) for failure in failures
    ] == [(0, 1, 1)]
    assert errors == {"RuntimeError": 1}
    assert timeouts == 0


def test_run_benchmark_records_explicit_round_worker_and_sample_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def coordinated_run_once(
        _session_factory: Any,
        *,
        context: benchmark.BenchmarkContext,
        timeout_seconds: int,
        round_index: int = -1,
        worker_index: int = -1,
        sample_index: int = -1,
        start_barrier: Any = None,
    ) -> benchmark.BenchmarkSample:
        del context, timeout_seconds
        if start_barrier is not None:
            start_barrier.wait()
        return benchmark.BenchmarkSample(
            round_index=round_index,
            worker_index=worker_index,
            sample_index=sample_index,
            duration_ms=1.0,
            truncated_results=0,
            results=(),
        )

    monkeypatch.setattr(benchmark, "run_once", coordinated_run_once)

    samples, failures, errors, _timeouts, _wall_seconds = benchmark.run_benchmark(
        MagicMock(),
        context=MagicMock(),
        concurrency=3,
        iterations=2,
        timeout_seconds=1,
    )

    assert errors == {}
    assert failures == []
    assert [
        (sample.round_index, sample.worker_index, sample.sample_index) for sample in samples
    ] == [
        (0, 0, 0),
        (0, 1, 1),
        (0, 2, 2),
        (1, 0, 3),
        (1, 1, 4),
        (1, 2, 5),
    ]


def test_run_benchmark_bounds_missing_barrier_participant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(benchmark, "BARRIER_TIMEOUT_SECONDS", 0.05)

    def missing_participant_run_once(
        _session_factory: Any,
        *,
        context: benchmark.BenchmarkContext,
        timeout_seconds: int,
        round_index: int = -1,
        worker_index: int = -1,
        sample_index: int = -1,
        start_barrier: Any = None,
    ) -> benchmark.BenchmarkSample:
        del context, timeout_seconds
        if worker_index != 0 and start_barrier is not None:
            start_barrier.wait()
        return benchmark.BenchmarkSample(
            round_index=round_index,
            worker_index=worker_index,
            sample_index=sample_index,
            duration_ms=1.0,
            truncated_results=0,
        )

    monkeypatch.setattr(benchmark, "run_once", missing_participant_run_once)

    started = perf_counter()
    samples, failures, errors, _timeouts, _wall_seconds = benchmark.run_benchmark(
        MagicMock(),
        context=MagicMock(),
        concurrency=2,
        iterations=1,
        timeout_seconds=1,
    )

    assert perf_counter() - started < 0.5
    assert [sample.worker_index for sample in samples] == [0]
    assert [
        (failure.round_index, failure.worker_index, failure.sample_index, failure.error_code)
        for failure in failures
    ] == [(0, 1, 1, "benchmark_start_barrier_broken")]
    assert errors == {"benchmark_start_barrier_broken": 1}


def test_run_benchmark_aborts_barrier_and_records_all_coordinates_on_submit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(benchmark, "BARRIER_TIMEOUT_SECONDS", 0.05)

    class SubmitFailsAfterOne(RealThreadPoolExecutor):
        submitted = 0

        def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Any:
            if self.submitted == 1:
                raise RuntimeError("submit failed")
            self.submitted += 1
            return super().submit(fn, *args, **kwargs)

    monkeypatch.setattr(benchmark, "ThreadPoolExecutor", SubmitFailsAfterOne)

    started = perf_counter()
    samples, failures, errors, _timeouts, _wall_seconds = benchmark.run_benchmark(
        MagicMock(),
        context=MagicMock(),
        concurrency=3,
        iterations=1,
        timeout_seconds=1,
    )

    assert perf_counter() - started < 0.5
    assert samples == []
    assert [
        (failure.round_index, failure.worker_index, failure.sample_index, failure.error_code)
        for failure in failures
    ] == [
        (0, 0, 0, "benchmark_start_barrier_broken"),
        (0, 1, 1, "RuntimeError"),
        (0, 2, 2, "benchmark_submit_aborted"),
    ]
    assert errors == {
        "benchmark_start_barrier_broken": 1,
        "RuntimeError": 1,
        "benchmark_submit_aborted": 1,
    }


def test_fingerprint_normalizes_opaque_ids_and_tracks_result_semantics() -> None:
    first = _chart_result(value=Decimal("12.30"), truncated=False)
    same_semantics_new_ids = _chart_result(value=Decimal("12.30"), truncated=False)
    changed_rows = _chart_result(value=Decimal("12.31"), truncated=False)
    changed_truncation = _chart_result(value=Decimal("12.30"), truncated=True)

    assert benchmark.result_fingerprint(first) == benchmark.result_fingerprint(
        same_semantics_new_ids
    )
    assert benchmark.result_fingerprint(first) != benchmark.result_fingerprint(changed_rows)
    assert benchmark.result_fingerprint(first) != benchmark.result_fingerprint(changed_truncation)


def test_benchmark_fixture_rejects_hash_tampering_and_row_mismatch(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    fixture_tool.generate_benchmark(fixture_dir, 100)

    with pytest.raises(ValueError, match="row count"):
        validate_benchmark_fixture(fixture_dir, expected_rows=101)

    fact_path = fixture_dir / "fact_sales.csv"
    content = fact_path.read_bytes()
    fact_path.write_bytes(content.replace(b"B000001-O-001", b"B000001-X-001", 1))
    with pytest.raises(ValueError, match="SHA-256"):
        validate_benchmark_fixture(fixture_dir, expected_rows=100)


def test_real_fixture_seed_runs_frozen_mix_and_repeats_fingerprints(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    fixture_tool.generate_benchmark(fixture_dir, 1_000)

    def execute_once(
        database_root: Path,
    ) -> tuple[benchmark.BenchmarkContext, benchmark.BenchmarkSample]:
        database_root.mkdir()
        with benchmark_database_engine(
            None,
            temporary_directory=database_root,
            pool_capacity=2,
        ) as engine:
            session_factory = create_session_factory(engine)
            principal, dataset_request = seed_benchmark(
                engine,
                session_factory,
                rows=1_000,
                fixture_dir=fixture_dir,
            )
            context = benchmark.seed_dashboard_benchmark(
                session_factory,
                principal=principal,
                dataset_id=dataset_request.dataset_id,
                rows=1_000,
                fixture_dir=fixture_dir,
            )
            sample = benchmark.run_once(
                session_factory,
                context=context,
                timeout_seconds=10,
            )
        return context, sample

    first_context, first = execute_once(tmp_path / "first")
    second_context, second = execute_once(tmp_path / "second")

    assert first_context.fixture_provenance["status"] == "pass"
    assert first_context.fixture_provenance["standard_fixture_consumed"] is True
    assert "benchmark_fixture_dir" not in first_context.fixture_provenance
    assert first_context.rls_expectation == second_context.rls_expectation
    assert len(first.results) == len(second.results) == 7
    assert all(result.client_duration_ms > 0 for result in first.results)
    assert all(result.elapsed_ms >= 0 for result in first.results)
    assert [result.fingerprint for result in first.results] == [
        result.fingerprint for result in second.results
    ]
    first_results = {result.scenario_name: result for result in first.results}
    assert (
        first_results["category_bar"].row_count
        == first_context.rls_expectation.unrestricted_row_count
    )
    assert (
        first_results["restricted_viewer_same_group"].row_count
        == first_context.rls_expectation.restricted_row_count
    )
    output = benchmark.build_output(
        dialect="sqlite",
        rows=1_000,
        concurrency=1,
        iterations=1,
        warmups=1,
        warmups_completed=1,
        queries_per_request=7,
        samples=[first],
        failures=(),
        errors={},
        timeouts=0,
        wall_seconds=first.duration_ms / 1_000,
        environment={},
        rls_expectation=first_context.rls_expectation,
        fixture_provenance=first_context.fixture_provenance,
    )
    scenario_results = cast(list[dict[str, object]], output["scenario_results"])
    performance_gate = cast(dict[str, object], output["performance_gate"])
    acceptance = cast(dict[str, object], output["acceptance"])
    assert all("client_duration_ms" in result for result in scenario_results)
    assert all("server_elapsed_ms" in result for result in scenario_results)
    assert performance_gate["passed"] is True
    assert acceptance["status"] == "pass"


def test_build_output_includes_aggregate_and_raw_evidence() -> None:
    samples = [
        benchmark.BenchmarkSample(
            sample_index=0,
            duration_ms=2.25,
            truncated_results=0,
            results=(
                benchmark.BenchmarkResultEvidence(
                    scenario_name="category_bar",
                    principal_name="administrator",
                    row_count=100,
                    fingerprint="admin-fingerprint",
                    truncated=False,
                ),
                benchmark.BenchmarkResultEvidence(
                    scenario_name="restricted_viewer_same_group",
                    principal_name="restricted_viewer",
                    row_count=100,
                    fingerprint="restricted-fingerprint",
                    truncated=False,
                ),
            ),
        ),
        benchmark.BenchmarkSample(
            sample_index=2,
            duration_ms=7.75,
            truncated_results=1,
            results=(
                benchmark.BenchmarkResultEvidence(
                    scenario_name="category_bar",
                    principal_name="administrator",
                    row_count=100,
                    fingerprint="admin-fingerprint",
                    truncated=False,
                ),
                benchmark.BenchmarkResultEvidence(
                    scenario_name="restricted_viewer_same_group",
                    principal_name="restricted_viewer",
                    row_count=100,
                    fingerprint="restricted-fingerprint",
                    truncated=True,
                ),
            ),
        ),
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
        failures=(),
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
    assert output["cache"] == {
        "state": "not_applicable",
        "application_cache_observed": False,
        "application_result_cache": "not_present_in_direct_service_execution_path",
        "cross_principal_cache_isolation": "not_evaluated",
        "warmup_scope": "database_and_os_page_cache_only",
    }
    assert output["percentile_method"] == "nearest-rank"
    assert output["environment"] == environment
    assert output["principal_names"] == ["administrator", "restricted_viewer"]
    assert output["scenario_names"] == [
        "category_bar",
        "restricted_viewer_same_group",
    ]
    rls_isolation = cast(dict[str, object], output["rls_isolation"])
    validation = cast(dict[str, object], output["run_validation"])
    acceptance = cast(dict[str, object], output["acceptance"])
    output_samples = cast(list[dict[str, object]], output["samples"])
    output_results = cast(list[dict[str, object]], output_samples[0]["results"])
    assert rls_isolation["evaluated"] is True
    assert rls_isolation["isolated"] is False
    assert validation["valid"] is False
    assert acceptance["status"] == "fail"
    assert output_results[0]["elapsed_ms"] == 0.0


def test_build_output_rejects_truncation_instability() -> None:
    samples = [
        benchmark.BenchmarkSample(
            sample_index=index,
            duration_ms=1.0,
            truncated_results=int(truncated),
            results=tuple(
                benchmark.BenchmarkResultEvidence(
                    scenario_name=scenario_name,
                    principal_name=principal_name,
                    row_count=(10 if scenario_name == "restricted_viewer_same_group" else 100),
                    fingerprint=f"fingerprint-{scenario_name}",
                    truncated=(truncated if scenario_name == "top_2" else False),
                    elapsed_ms=0.5,
                )
                for scenario_name, principal_name in benchmark.SCENARIO_PRINCIPALS.items()
            ),
        )
        for index, truncated in enumerate((False, True))
    ]

    output = benchmark.build_output(
        dialect="sqlite",
        rows=100,
        concurrency=1,
        iterations=2,
        warmups=5,
        warmups_completed=5,
        queries_per_request=7,
        samples=samples,
        failures=(),
        errors={},
        timeouts=0,
        wall_seconds=0.5,
        environment={},
        rls_expectation=benchmark.RlsExpectation(
            unrestricted_row_count=100,
            restricted_row_count=10,
        ),
        fixture_provenance={"status": "partial"},
    )

    scenario_results = cast(list[dict[str, object]], output["scenario_results"])
    scenarios = {cast(str, item["scenario_name"]): item for item in scenario_results}
    validation = cast(dict[str, object], output["run_validation"])
    assert scenarios["top_2"]["stable"] is False
    assert validation["valid"] is False


def test_build_output_rejects_client_p95_above_performance_gate() -> None:
    restricted_rows: tuple[dict[str, object], ...] = (
        {"dimension": "Hardware", "value_1": "100.00"},
    )
    results = tuple(
        benchmark.BenchmarkResultEvidence(
            scenario_name=scenario_name,
            principal_name=principal_name,
            row_count=(
                1
                if scenario_name == "restricted_viewer_same_group"
                else 2
                if scenario_name == "category_bar"
                else 100
            ),
            fingerprint=f"fingerprint-{scenario_name}",
            truncated=scenario_name == "top_2",
            canonical_rows=(
                restricted_rows if scenario_name == "restricted_viewer_same_group" else ()
            ),
            canonical_row_fingerprint=(
                benchmark.canonical_rows_fingerprint(restricted_rows)
                if scenario_name == "restricted_viewer_same_group"
                else None
            ),
            client_duration_ms=(5_001.0 if scenario_name == "top_2" else 10.0),
            elapsed_ms=5.0,
        )
        for scenario_name, principal_name in benchmark.SCENARIO_PRINCIPALS.items()
    )

    output = benchmark.build_output(
        dialect="sqlite",
        rows=100,
        concurrency=1,
        iterations=1,
        warmups=5,
        warmups_completed=5,
        queries_per_request=7,
        samples=[
            benchmark.BenchmarkSample(
                sample_index=0,
                duration_ms=5_061.0,
                truncated_results=1,
                results=results,
                round_index=0,
                worker_index=0,
            )
        ],
        failures=(),
        errors={},
        timeouts=0,
        wall_seconds=5.061,
        environment={},
        rls_expectation=benchmark.RlsExpectation(
            unrestricted_row_count=2,
            restricted_row_count=1,
            unrestricted_source_row_count=100,
            restricted_source_row_count=10,
            restricted_canonical_rows=restricted_rows,
            fixture_oracle_trusted=True,
        ),
        fixture_provenance={"status": "pass", "standard_fixture_consumed": True},
    )

    validation = cast(dict[str, object], output["run_validation"])
    performance_gate = cast(dict[str, object], output["performance_gate"])
    acceptance = cast(dict[str, object], output["acceptance"])
    scenario_results = cast(list[dict[str, object]], output["scenario_results"])
    top_2 = next(result for result in scenario_results if result["scenario_name"] == "top_2")
    client_timing = cast(dict[str, object], top_2["client_duration_ms"])
    server_timing = cast(dict[str, object], top_2["server_elapsed_ms"])

    assert validation["valid"] is True
    assert performance_gate == {
        "metric": "maximum_representative_scenario_client_p95_ms",
        "threshold_ms": 5_000.0,
        "observed_ms": 5_001.0,
        "representative_scenario_count": 7,
        "evaluated_scenario_count": 7,
        "missing_scenarios": [],
        "passed": False,
    }
    assert client_timing == {"p50": 5_001.0, "p95": 5_001.0, "max": 5_001.0}
    assert server_timing == {"p50": 5.0, "p95": 5.0, "max": 5.0}
    assert output["sample_duration_semantics"] == {
        "scope": "seven_query_serial_worker_round",
        "purpose": "throughput_and_worker_round_only",
        "used_for_single_query_gate": False,
        "single_query_gate_source": "scenario_results.client_duration_ms.p95",
    }
    assert acceptance["performance_gate_status"] == "fail"
    assert acceptance["status"] == "fail"


@pytest.mark.parametrize(
    "actual_rows",
    [
        (
            {"dimension": "Hardware", "value_1": "225.00"},
            {"dimension": "Services", "value_1": "40.00"},
            {"dimension": None, "value_1": "35.00"},
        ),
        (
            {"dimension": "Hardware", "value_1": "105.00"},
            {"dimension": "Services", "value_1": "40.00"},
            {"dimension": None, "value_1": "30.00"},
        ),
    ],
    ids=("wrong-region-same-category-count", "partial-cross-region-leak"),
)
def test_rls_fixture_oracle_rejects_wrong_region_values_with_same_row_count(
    actual_rows: tuple[dict[str, object], ...],
) -> None:
    expected_rows: tuple[dict[str, object], ...] = (
        {"dimension": "Hardware", "value_1": "100.00"},
        {"dimension": "Services", "value_1": "40.00"},
        {"dimension": None, "value_1": "30.00"},
    )
    output = _build_complete_output(
        restricted_rows=actual_rows,
        expectation=benchmark.RlsExpectation(
            unrestricted_row_count=3,
            restricted_row_count=3,
            unrestricted_source_row_count=10,
            restricted_source_row_count=5,
            restricted_canonical_rows=expected_rows,
            fixture_oracle_trusted=True,
        ),
    )

    rls = cast(dict[str, object], output["rls_isolation"])
    oracle = cast(dict[str, object], rls["fixture_oracle"])
    validation = cast(dict[str, object], output["run_validation"])
    acceptance = cast(dict[str, object], output["acceptance"])
    assert rls["expected_rows_match"] is True
    assert oracle["canonical_rows_match"] is False
    assert oracle["status"] == "fail"
    assert rls["isolated"] is False
    assert validation["valid"] is False
    assert acceptance["status"] == "fail"


def test_rls_oracle_requires_trusted_fixture_provenance() -> None:
    expected_rows: tuple[dict[str, object], ...] = (
        {"dimension": "Hardware", "value_1": "100.00"},
        {"dimension": "Services", "value_1": "40.00"},
        {"dimension": None, "value_1": "30.00"},
    )
    output = _build_complete_output(
        restricted_rows=expected_rows,
        expectation=benchmark.RlsExpectation(
            unrestricted_row_count=3,
            restricted_row_count=3,
            unrestricted_source_row_count=10,
            restricted_source_row_count=5,
            restricted_canonical_rows=expected_rows,
            fixture_oracle_trusted=False,
        ),
    )

    rls = cast(dict[str, object], output["rls_isolation"])
    oracle = cast(dict[str, object], rls["fixture_oracle"])
    acceptance = cast(dict[str, object], output["acceptance"])
    assert oracle["trusted"] is False
    assert oracle["status"] == "unavailable"
    assert rls["isolated"] is False
    assert acceptance["status"] == "fail"


def test_seeded_context_measures_frozen_mix_and_proves_rls_isolation(tmp_path: Path) -> None:
    with benchmark_database_engine(
        None,
        temporary_directory=tmp_path,
        pool_capacity=2,
    ) as engine:
        session_factory = create_session_factory(engine)
        principal, dataset_request = seed_benchmark(engine, session_factory, rows=1_000)
        context = benchmark.seed_dashboard_benchmark(
            session_factory,
            principal=principal,
            dataset_id=dataset_request.dataset_id,
            rows=1_000,
        )
        sample = benchmark.run_once(
            session_factory,
            context=context,
            timeout_seconds=10,
        )

    assert [scenario.name for scenario in context.scenarios] == [
        "full_kpi",
        "category_bar",
        "category_region_stacked",
        "month_trend",
        "top_2",
        "global_page_component_filters",
        "restricted_viewer_same_group",
    ]
    assert {scenario.principal_name for scenario in context.scenarios} == {
        "administrator",
        "editor",
        "restricted_viewer",
    }
    assert len(sample.results) == 7
    evidence = {result.scenario_name: result for result in sample.results}
    assert evidence["full_kpi"].row_count == 1
    assert evidence["month_trend"].row_count == 12
    assert evidence["top_2"].row_count == 2
    assert evidence["category_bar"].row_count == context.rls_expectation.unrestricted_row_count
    assert (
        evidence["restricted_viewer_same_group"].row_count
        == context.rls_expectation.restricted_row_count
    )
    assert (
        evidence["category_bar"].fingerprint != evidence["restricted_viewer_same_group"].fingerprint
    )
    assert context.fixture_provenance["fixture_version"] == "m3-star-v2"
    assert context.fixture_provenance["standard_fixture_consumed"] is False
    assert context.fixture_provenance["status"] == "partial"
    principals = {scenario.principal_name: scenario.principal for scenario in context.scenarios}
    assert principals["administrator"].has_permission("datasets:manage")
    assert not principals["editor"].has_permission("datasets:manage")
    assert not principals["restricted_viewer"].has_permission("dashboards:edit")


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


def test_producer_provenance_hashes_dirty_sources_without_leaking_content_or_paths(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "producer-repository"
    sources = {
        "scripts/benchmark_m2_queries.py": "M2_SOURCE = True\n",
        "scripts/benchmark_m3_chart_queries.py": "M3_SOURCE = True\n",
        "spikes/m3/quality/fixture_tool.py": "FIXTURE_TOOL = True\n",
        "spikes/m3/quality/fixture/v2/manifest.json": '{"fixture_version":"m3-star-v2"}\n',
    }
    for relative_path, content in sources.items():
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _run_git(repository, "init")
    _run_git(repository, "config", "user.email", "benchmark@example.invalid")
    _run_git(repository, "config", "user.name", "Benchmark Test")
    _run_git(repository, "config", "core.autocrlf", "false")
    _run_git(repository, "add", ".")
    _run_git(repository, "commit", "-m", "test: seed producer sources")

    clean = benchmark.build_producer_provenance(repository)
    secret = "benchmark-secret-token-value"
    (repository / "scripts/benchmark_m3_chart_queries.py").write_text(
        f'M3_SOURCE = True\nTOKEN = "{secret}"\n',
        encoding="utf-8",
    )
    dirty = benchmark.build_producer_provenance(repository)
    serialized = json.dumps(dirty, sort_keys=True)

    assert clean["worktree_state"] == "clean"
    assert dirty["worktree_state"] == "dirty"
    assert clean["head_sha"] == dirty["head_sha"]
    assert clean["worktree_snapshot_sha256"] != dirty["worktree_snapshot_sha256"]
    assert clean["source_content_sha256"] != dirty["source_content_sha256"]
    assert dirty["producer_sources_dirty"] is True
    assert secret not in serialized
    assert str(repository) not in serialized


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
    context = MagicMock(
        requests=(MagicMock(), MagicMock(), MagicMock()),
        rls_expectation=benchmark.RlsExpectation(
            unrestricted_row_count=100,
            restricted_row_count=10,
        ),
        fixture_provenance={"status": "partial"},
    )
    run_once = MagicMock(
        return_value=benchmark.BenchmarkSample(
            sample_index=-1,
            duration_ms=1.0,
            truncated_results=0,
        )
    )
    producer_provenance: dict[str, object] = {
        "head_sha": "a" * 40,
        "worktree_state": "dirty",
        "dirty": True,
        "producer_sources_dirty": True,
        "worktree_snapshot_sha256": "b" * 64,
        "tracked_diff_sha256": "c" * 64,
        "untracked_target_source_count": 0,
        "source_content_sha256": {
            "benchmark_m2_queries": "d" * 64,
            "benchmark_m3_chart_queries": "e" * 64,
            "fixture_tool": "f" * 64,
            "fixture_v2_manifest": "0" * 64,
        },
    }
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
        "build_producer_provenance",
        MagicMock(return_value=producer_provenance),
    )
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
                [],
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
    assert result == 1
    assert run_once.call_count == 5
    assert stdout_json == file_json
    assert stdout_json["warmups"] == 5
    assert stdout_json["warmups_completed"] == 5
    assert stdout_json["run_validation"]["valid"] is False
    assert stdout_json["git_sha"] == "a" * 40
    assert stdout_json["producer_provenance"] == producer_provenance


def _chart_result(*, value: Decimal, truncated: bool) -> DashboardChartResult:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return DashboardChartResult(
        request_id=uuid4(),
        component_id=uuid4(),
        columns=(
            ChartColumn(
                slot_key="amount",
                query_alias="value_1",
                resource_kind="field",
                resource_id=uuid4(),
                aggregate="sum",
                label="Amount",
                data_type="decimal",
                unit="CNY",
            ),
        ),
        rows=({"value_1": value},),
        truncated=truncated,
        elapsed_ms=1.5,
        dataset_version=1,
        metric_version_ids=(uuid4(),),
        source_batch_ids=(uuid4(), uuid4()),
        resolved_filters=(
            ResolvedFilterEvidence(
                scope="global",
                field_id=uuid4(),
                field_type="date",
                semantic="absolute",
                timezone="Asia/Hong_Kong",
                start=date(2026, 1, 1),
                end=date(2026, 2, 1),
                resolved_at=now,
            ),
        ),
        warnings=(),
    )


def _build_complete_output(
    *,
    restricted_rows: tuple[dict[str, object], ...],
    expectation: benchmark.RlsExpectation,
) -> dict[str, object]:
    canonical_restricted_rows = benchmark.canonicalize_rows(restricted_rows)
    results = tuple(
        benchmark.BenchmarkResultEvidence(
            scenario_name=scenario_name,
            principal_name=principal_name,
            row_count=(
                expectation.restricted_row_count
                if scenario_name == "restricted_viewer_same_group"
                else expectation.unrestricted_row_count
                if scenario_name == "category_bar"
                else 4
            ),
            fingerprint=f"fingerprint-{scenario_name}",
            truncated=scenario_name == "top_2",
            canonical_rows=(
                canonical_restricted_rows if scenario_name == "restricted_viewer_same_group" else ()
            ),
            canonical_row_fingerprint=(
                benchmark.canonical_rows_fingerprint(canonical_restricted_rows)
                if scenario_name == "restricted_viewer_same_group"
                else "not-evaluated"
            ),
            client_duration_ms=10.0,
            elapsed_ms=5.0,
        )
        for scenario_name, principal_name in benchmark.SCENARIO_PRINCIPALS.items()
    )
    return benchmark.build_output(
        dialect="sqlite",
        rows=10,
        concurrency=1,
        iterations=1,
        warmups=5,
        warmups_completed=5,
        queries_per_request=7,
        samples=[
            benchmark.BenchmarkSample(
                sample_index=0,
                duration_ms=70.0,
                truncated_results=1,
                results=results,
                round_index=0,
                worker_index=0,
            )
        ],
        failures=(),
        errors={},
        timeouts=0,
        wall_seconds=0.07,
        environment={},
        rls_expectation=expectation,
        fixture_provenance={"status": "pass", "standard_fixture_consumed": True},
    )


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


def _run_git(repository: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
