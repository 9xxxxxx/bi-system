from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier, BrokenBarrierError
from time import perf_counter
from typing import Literal, cast
from uuid import UUID, uuid4

if __package__:
    from scripts.benchmark_m2_queries import (
        BenchmarkFixture,
        benchmark_database_engine,
        percentile,
        seed_benchmark,
        validate_benchmark_fixture,
    )
else:
    from benchmark_m2_queries import (
        BenchmarkFixture,
        benchmark_database_engine,
        percentile,
        seed_benchmark,
        validate_benchmark_fixture,
    )
from bi_system.dashboards.chart_contracts import (
    DashboardChartQueryRequest,
    RuntimeChartFilterScopes,
)
from bi_system.dashboards.chart_query import (
    DashboardChartQueryError,
    DashboardChartResult,
    execute_dashboard_chart_query,
)
from bi_system.db.models import (
    Dashboard,
    DashboardComponent,
    DashboardPage,
    DashboardPermission,
    DashboardVersion,
    DatasetField,
    RowPolicy,
    RowPolicyAssignment,
    User,
)
from bi_system.db.session import create_session_factory
from bi_system.identity import QueryPrincipal
from sqlalchemy import select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

type PrincipalName = Literal["administrator", "editor", "restricted_viewer"]

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "spikes" / "m3" / "quality" / "fixture" / "v2"
SCENARIO_PRINCIPALS: dict[str, PrincipalName] = {
    "full_kpi": "administrator",
    "category_bar": "administrator",
    "category_region_stacked": "administrator",
    "month_trend": "editor",
    "top_2": "editor",
    "global_page_component_filters": "editor",
    "restricted_viewer_same_group": "restricted_viewer",
}
EXPECTED_SCENARIO_NAMES = tuple(SCENARIO_PRINCIPALS)
EXPECTED_PRINCIPAL_NAMES: tuple[PrincipalName, ...] = (
    "administrator",
    "editor",
    "restricted_viewer",
)
SINGLE_QUERY_P95_THRESHOLD_MS = 5_000.0
BARRIER_TIMEOUT_SECONDS = 5.0
PRODUCER_SOURCES: tuple[tuple[str, str], ...] = (
    ("benchmark_m2_queries", "scripts/benchmark_m2_queries.py"),
    ("benchmark_m3_chart_queries", "scripts/benchmark_m3_chart_queries.py"),
    ("fixture_tool", "spikes/m3/quality/fixture_tool.py"),
    ("fixture_v2_manifest", "spikes/m3/quality/fixture/v2/manifest.json"),
)
RUNTIME_PRINCIPAL_PERMISSIONS: dict[PrincipalName, frozenset[str]] = {
    "administrator": frozenset(
        {"dashboards:manage", "dashboards:view", "datasets:manage", "datasets:query"}
    ),
    "editor": frozenset({"dashboards:manage", "dashboards:view", "datasets:query"}),
    "restricted_viewer": frozenset({"dashboards:view", "datasets:query"}),
}


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    name: str
    principal_name: PrincipalName
    principal: QueryPrincipal
    request: DashboardChartQueryRequest


@dataclass(frozen=True, slots=True)
class BenchmarkContext:
    scenarios: tuple[BenchmarkScenario, ...]
    rls_expectation: RlsExpectation
    fixture_provenance: dict[str, object]

    @property
    def requests(self) -> tuple[DashboardChartQueryRequest, ...]:
        return tuple(scenario.request for scenario in self.scenarios)


@dataclass(frozen=True, slots=True)
class BenchmarkResultEvidence:
    scenario_name: str
    principal_name: PrincipalName
    row_count: int
    fingerprint: str
    truncated: bool
    canonical_rows: tuple[dict[str, object], ...] = ()
    canonical_row_fingerprint: str | None = None
    client_duration_ms: float = 0.0
    elapsed_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class RlsExpectation:
    unrestricted_row_count: int
    restricted_row_count: int
    unrestricted_source_row_count: int | None = None
    restricted_source_row_count: int | None = None
    restricted_canonical_rows: tuple[dict[str, object], ...] = ()
    fixture_oracle_trusted: bool = False


@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    sample_index: int
    duration_ms: float
    truncated_results: int
    results: tuple[BenchmarkResultEvidence, ...] = ()
    round_index: int = -1
    worker_index: int = -1


@dataclass(frozen=True, slots=True)
class BenchmarkFailureEvidence:
    round_index: int
    worker_index: int
    sample_index: int
    error_code: str
    timeout: bool


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark governed M3 dashboard chart queries")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--database-url")
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if min(args.rows, args.concurrency, args.iterations, args.warmups, args.timeout_seconds) < 1:
        parser.error("rows, concurrency, iterations, warmups, and timeout must be positive")
    if args.database_url and make_url(args.database_url).get_backend_name() != "postgresql":
        parser.error("database-url must use the PostgreSQL dialect")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    with (
        tempfile.TemporaryDirectory(prefix="bi-m3-chart-benchmark-") as temporary_directory,
        benchmark_database_engine(
            args.database_url,
            temporary_directory=Path(temporary_directory),
            pool_capacity=max(2, args.concurrency * 2),
        ) as engine,
    ):
        session_factory = create_session_factory(engine)
        principal, dataset_request = seed_benchmark(
            engine,
            session_factory,
            rows=args.rows,
            fixture_dir=args.fixture_dir,
        )
        context = seed_dashboard_benchmark(
            session_factory,
            principal=principal,
            dataset_id=dataset_request.dataset_id,
            rows=args.rows,
            fixture_dir=args.fixture_dir,
        )
        warmups_completed = 0
        for _ in range(args.warmups):
            run_once(
                session_factory,
                context=context,
                timeout_seconds=args.timeout_seconds,
            )
            warmups_completed += 1
        samples, failures, errors, timeouts, wall_seconds = run_benchmark(
            session_factory,
            context=context,
            concurrency=args.concurrency,
            iterations=args.iterations,
            timeout_seconds=args.timeout_seconds,
        )
        dialect = engine.dialect.name
        environment = environment_metadata(engine)

    producer_provenance = build_producer_provenance()
    output = build_output(
        dialect=dialect,
        rows=args.rows,
        concurrency=args.concurrency,
        iterations=args.iterations,
        warmups=args.warmups,
        warmups_completed=warmups_completed,
        queries_per_request=len(context.requests),
        samples=samples,
        failures=failures,
        errors=errors,
        timeouts=timeouts,
        wall_seconds=wall_seconds,
        environment=environment,
        rls_expectation=context.rls_expectation,
        fixture_provenance=context.fixture_provenance,
        producer_provenance=producer_provenance,
    )
    serialized = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    acceptance = cast(dict[str, object], output["acceptance"])
    return 0 if acceptance["status"] == "pass" else 1


def build_output(
    *,
    dialect: str,
    rows: int,
    concurrency: int,
    iterations: int,
    warmups: int,
    warmups_completed: int,
    queries_per_request: int,
    samples: list[BenchmarkSample],
    failures: Sequence[BenchmarkFailureEvidence],
    errors: dict[str, int],
    timeouts: int,
    wall_seconds: float,
    environment: dict[str, object],
    rls_expectation: RlsExpectation | None = None,
    fixture_provenance: dict[str, object] | None = None,
    producer_provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    durations = [sample.duration_ms for sample in samples]
    completed = len(samples)
    result_evidence = [result for sample in samples for result in sample.results]
    principal_names = _ordered_unique(result.principal_name for result in result_evidence)
    scenario_names = _ordered_unique(result.scenario_name for result in result_evidence)
    requested = concurrency * iterations
    scenario_results = _scenario_results(result_evidence, expected_sample_count=requested)
    performance_gate = _performance_gate(scenario_results)
    rls_isolation = _rls_isolation(result_evidence, rls_expectation)
    run_validation = _run_validation(
        requested=requested,
        completed=completed,
        errors=errors,
        principal_names=principal_names,
        scenario_names=scenario_names,
        scenario_results=scenario_results,
        rls_isolation=rls_isolation,
    )
    provenance = fixture_provenance or {
        "status": "partial",
        "standard_fixture_consumed": False,
        "reason": "fixture provenance was not supplied",
    }
    producer = producer_provenance or {"head_sha": "unavailable"}
    if run_validation["valid"] is not True or performance_gate["passed"] is not True:
        acceptance_status = "fail"
    elif provenance.get("status") == "pass":
        acceptance_status = "pass"
    else:
        acceptance_status = "partial"
    acceptance_limitations = [
        "The direct service benchmark has no application result cache; "
        "cache isolation is not applicable."
    ]
    if provenance.get("status") != "pass":
        acceptance_limitations.append(
            "The synthetic scale does not consume the signed fixture-v2 row files."
        )
    return {
        "git_sha": producer["head_sha"],
        "producer_provenance": producer,
        "dialect": dialect,
        "rows": rows,
        "concurrency": concurrency,
        "iterations": iterations,
        "warmups": warmups,
        "warmups_completed": warmups_completed,
        "requests": requested,
        "queries_per_request": queries_per_request,
        "completed": completed,
        "errors": errors,
        "error_count": sum(errors.values()),
        "timeouts": timeouts,
        "truncated_results": sum(sample.truncated_results for sample in samples),
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": percentile(durations, 0.95),
        "max_ms": round(max(durations), 3) if durations else None,
        "sample_duration_semantics": {
            "scope": "seven_query_serial_worker_round",
            "purpose": "throughput_and_worker_round_only",
            "used_for_single_query_gate": False,
            "single_query_gate_source": "scenario_results.client_duration_ms.p95",
        },
        "cache": {
            "state": "not_applicable",
            "application_cache_observed": False,
            "application_result_cache": "not_present_in_direct_service_execution_path",
            "cross_principal_cache_isolation": "not_evaluated",
            "warmup_scope": "database_and_os_page_cache_only",
        },
        "percentile_method": "nearest-rank",
        "throughput_rps": round(completed / wall_seconds, 3) if wall_seconds else 0,
        "wall_seconds": round(wall_seconds, 3),
        "principal_names": principal_names,
        "expected_principal_names": list(EXPECTED_PRINCIPAL_NAMES),
        "scenario_names": scenario_names,
        "expected_scenario_names": list(EXPECTED_SCENARIO_NAMES),
        "scenario_results": scenario_results,
        "performance_gate": performance_gate,
        "rls_isolation": rls_isolation,
        "rounds": _round_results(samples, failures, concurrency=concurrency, iterations=iterations),
        "failures": [
            {
                "round_index": failure.round_index,
                "worker_index": failure.worker_index,
                "sample_index": failure.sample_index,
                "error_code": failure.error_code,
                "timeout": failure.timeout,
            }
            for failure in failures
        ],
        "samples": [
            {
                "round_index": sample.round_index,
                "worker_index": sample.worker_index,
                "sample_index": sample.sample_index,
                "duration_ms": sample.duration_ms,
                "truncated_results": sample.truncated_results,
                "results": [
                    {
                        "scenario_name": result.scenario_name,
                        "principal_name": result.principal_name,
                        "row_count": result.row_count,
                        "fingerprint": result.fingerprint,
                        "truncated": result.truncated,
                        "canonical_rows": result.canonical_rows,
                        "canonical_row_fingerprint": result.canonical_row_fingerprint,
                        "client_duration_ms": result.client_duration_ms,
                        "elapsed_ms": result.elapsed_ms,
                    }
                    for result in sample.results
                ],
            }
            for sample in samples
        ],
        "environment": environment,
        "fixture_provenance": provenance,
        "run_validation": run_validation,
        "acceptance": {
            "status": acceptance_status,
            "run_evidence_valid": run_validation["valid"],
            "standard_fixture_status": provenance.get("status", "partial"),
            "performance_gate_status": ("pass" if performance_gate["passed"] is True else "fail"),
            "application_result_cache_status": "not_applicable",
            "limitations": acceptance_limitations,
        },
    }


def _ordered_unique(values: Iterable[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        if value not in ordered:
            ordered.append(value)
    return ordered


def _scenario_results(
    results: list[BenchmarkResultEvidence],
    *,
    expected_sample_count: int,
) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for scenario_name in EXPECTED_SCENARIO_NAMES:
        matching = [result for result in results if result.scenario_name == scenario_name]
        row_counts = sorted({result.row_count for result in matching})
        fingerprints = sorted({result.fingerprint for result in matching})
        truncation_values = sorted({result.truncated for result in matching})
        client_durations = [result.client_duration_ms for result in matching]
        server_durations = [result.elapsed_ms for result in matching]
        summaries.append(
            {
                "scenario_name": scenario_name,
                "principal_name": SCENARIO_PRINCIPALS[scenario_name],
                "sample_count": len(matching),
                "row_counts": row_counts,
                "fingerprints": fingerprints,
                "truncated_values": truncation_values,
                "client_duration_ms": {
                    "p50": percentile(client_durations, 0.50),
                    "p95": percentile(client_durations, 0.95),
                    "max": round(max(client_durations), 3) if client_durations else None,
                },
                "server_elapsed_ms": {
                    "p50": percentile(server_durations, 0.50),
                    "p95": percentile(server_durations, 0.95),
                    "max": round(max(server_durations), 3) if server_durations else None,
                },
                "stable": len(matching) == expected_sample_count
                and len(row_counts) == 1
                and len(fingerprints) == 1
                and len(truncation_values) == 1,
            }
        )
    return summaries


def _performance_gate(
    scenario_results: list[dict[str, object]],
) -> dict[str, object]:
    client_p95_values: list[float] = []
    missing_scenarios: list[str] = []
    for summary in scenario_results:
        timing = cast(dict[str, object], summary["client_duration_ms"])
        p95 = timing["p95"]
        if isinstance(p95, int | float):
            client_p95_values.append(float(p95))
        else:
            missing_scenarios.append(cast(str, summary["scenario_name"]))
    observed = max(client_p95_values) if client_p95_values else None
    complete = len(client_p95_values) == len(EXPECTED_SCENARIO_NAMES)
    passed = complete and observed is not None and observed <= SINGLE_QUERY_P95_THRESHOLD_MS
    return {
        "metric": "maximum_representative_scenario_client_p95_ms",
        "threshold_ms": SINGLE_QUERY_P95_THRESHOLD_MS,
        "observed_ms": round(observed, 3) if observed is not None else None,
        "representative_scenario_count": len(EXPECTED_SCENARIO_NAMES),
        "evaluated_scenario_count": len(client_p95_values),
        "missing_scenarios": missing_scenarios,
        "passed": passed,
    }


def _rls_isolation(
    results: list[BenchmarkResultEvidence],
    expectation: RlsExpectation | None,
) -> dict[str, object]:
    unrestricted = {
        result.fingerprint for result in results if result.scenario_name == "category_bar"
    }
    restricted_results = [
        result for result in results if result.scenario_name == "restricted_viewer_same_group"
    ]
    restricted = {result.fingerprint for result in restricted_results}
    evaluated = bool(unrestricted and restricted)
    unrestricted_rows = sorted(
        {result.row_count for result in results if result.scenario_name == "category_bar"}
    )
    restricted_rows = sorted(
        {
            result.row_count
            for result in results
            if result.scenario_name == "restricted_viewer_same_group"
        }
    )
    expected_rows_match = (
        expectation is not None
        and unrestricted_rows == [expectation.unrestricted_row_count]
        and restricted_rows == [expectation.restricted_row_count]
    )
    unrestricted_source_rows = (
        expectation.unrestricted_source_row_count if expectation is not None else None
    )
    restricted_source_rows = (
        expectation.restricted_source_row_count if expectation is not None else None
    )
    restricted_subset = expectation is not None and (
        (
            unrestricted_source_rows is not None
            and restricted_source_rows is not None
            and restricted_source_rows < unrestricted_source_rows
        )
        or (
            unrestricted_source_rows is None
            and restricted_source_rows is None
            and expectation.restricted_row_count < expectation.unrestricted_row_count
        )
    )
    expected_canonical_rows = (
        expectation.restricted_canonical_rows if expectation is not None else ()
    )
    oracle_trusted = expectation is not None and expectation.fixture_oracle_trusted
    expected_canonical_row_fingerprint = (
        canonical_rows_fingerprint(expected_canonical_rows) if oracle_trusted else None
    )
    actual_canonical_row_fingerprints = sorted(
        {
            result.canonical_row_fingerprint
            for result in restricted_results
            if result.canonical_row_fingerprint is not None
        }
    )
    actual_canonical_rows: list[tuple[dict[str, object], ...]] = []
    for result in restricted_results:
        if result.canonical_rows not in actual_canonical_rows:
            actual_canonical_rows.append(result.canonical_rows)
    canonical_rows_match = (
        oracle_trusted
        and bool(restricted_results)
        and all(
            result.canonical_rows == expected_canonical_rows
            and result.canonical_row_fingerprint == expected_canonical_row_fingerprint
            for result in restricted_results
        )
    )
    fixture_oracle = {
        "trusted": oracle_trusted,
        "status": ("pass" if canonical_rows_match else "fail" if oracle_trusted else "unavailable"),
        "source": (
            "verified fixture fact_sales.csv joined to dim_product.csv and filtered to R-NORTH"
            if oracle_trusted
            else None
        ),
        "expected_canonical_rows": expected_canonical_rows,
        "actual_canonical_rows": actual_canonical_rows,
        "expected_canonical_row_fingerprint": expected_canonical_row_fingerprint,
        "actual_canonical_row_fingerprints": actual_canonical_row_fingerprints,
        "canonical_rows_match": canonical_rows_match,
    }
    return {
        "unrestricted_scenario": "category_bar",
        "restricted_scenario": "restricted_viewer_same_group",
        "fingerprints_distinct": evaluated and unrestricted.isdisjoint(restricted),
        "evaluated": evaluated,
        "unrestricted_row_counts": unrestricted_rows,
        "restricted_row_counts": restricted_rows,
        "expected_unrestricted_row_count": (
            expectation.unrestricted_row_count if expectation is not None else None
        ),
        "expected_restricted_row_count": (
            expectation.restricted_row_count if expectation is not None else None
        ),
        "expected_rows_match": expected_rows_match,
        "expected_unrestricted_source_row_count": unrestricted_source_rows,
        "expected_restricted_source_row_count": restricted_source_rows,
        "restricted_subset": restricted_subset,
        "fixture_oracle": fixture_oracle,
        "isolated": evaluated
        and unrestricted.isdisjoint(restricted)
        and expected_rows_match
        and restricted_subset
        and canonical_rows_match,
    }


def _run_validation(
    *,
    requested: int,
    completed: int,
    errors: dict[str, int],
    principal_names: list[str],
    scenario_names: list[str],
    scenario_results: list[dict[str, object]],
    rls_isolation: dict[str, object],
) -> dict[str, object]:
    issues: list[str] = []
    if completed != requested:
        issues.append("completed sample count does not match requested sample count")
    if errors:
        issues.append("one or more benchmark samples failed")
    if set(principal_names) != set(EXPECTED_PRINCIPAL_NAMES):
        issues.append("the expected three principals were not all observed")
    if set(scenario_names) != set(EXPECTED_SCENARIO_NAMES):
        issues.append("the expected seven scenarios were not all observed")
    if any(summary["stable"] is not True for summary in scenario_results):
        issues.append("one or more scenario results were incomplete or unstable")
    if rls_isolation["isolated"] is not True:
        issues.append(
            "the frozen RLS fixture-oracle row values and isolation contract did not hold"
        )
    return {"valid": not issues, "issues": issues}


def _round_results(
    samples: list[BenchmarkSample],
    failures: Sequence[BenchmarkFailureEvidence],
    *,
    concurrency: int,
    iterations: int,
) -> list[dict[str, object]]:
    rounds: list[dict[str, object]] = []
    for round_index in range(iterations):
        completed = [sample for sample in samples if sample.round_index == round_index]
        failed = [failure for failure in failures if failure.round_index == round_index]
        rounds.append(
            {
                "round_index": round_index,
                "expected_workers": concurrency,
                "completed_workers": sorted(sample.worker_index for sample in completed),
                "failed_workers": sorted(failure.worker_index for failure in failed),
                "sample_indices": sorted(sample.sample_index for sample in completed),
                "complete": len(completed) == concurrency and not failed,
            }
        )
    return rounds


def build_producer_provenance(
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    source_paths = [relative_path for _label, relative_path in PRODUCER_SOURCES]
    head_sha = _git_output(repository_root, "rev-parse", "HEAD").decode("ascii").strip()
    if not head_sha:
        raise RuntimeError("Git HEAD was empty while collecting benchmark provenance")
    status = _git_output(
        repository_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    tracked_diff = _git_output(
        repository_root,
        "diff",
        "--binary",
        "--no-ext-diff",
        "--no-renames",
        "HEAD",
        "--",
        *source_paths,
    )
    untracked_output = _git_output(
        repository_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *source_paths,
    )
    untracked_paths = {
        line.decode("utf-8").replace("\\", "/") for line in untracked_output.splitlines() if line
    }
    source_content_sha256 = {
        label: _sha256(repository_root / relative_path) for label, relative_path in PRODUCER_SOURCES
    }
    untracked_sources = sorted(
        label for label, relative_path in PRODUCER_SOURCES if relative_path in untracked_paths
    )
    tracked_diff_sha256 = hashlib.sha256(tracked_diff).hexdigest()
    snapshot_payload = {
        "schema_version": 1,
        "head_sha": head_sha,
        "tracked_diff_sha256": tracked_diff_sha256,
        "untracked_source_content_sha256": {
            label: source_content_sha256[label] for label in untracked_sources
        },
    }
    snapshot = json.dumps(
        snapshot_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    dirty = bool(status.strip())
    return {
        "head_sha": head_sha,
        "worktree_state": "dirty" if dirty else "clean",
        "dirty": dirty,
        "producer_sources_dirty": bool(tracked_diff or untracked_sources),
        "worktree_snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
        "tracked_diff_sha256": tracked_diff_sha256,
        "untracked_target_source_count": len(untracked_sources),
        "source_content_sha256": source_content_sha256,
        "snapshot_scope": (
            "HEAD plus targeted producer tracked diff and untracked producer source content"
        ),
    }


def _git_output(repository_root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Unable to collect benchmark producer Git provenance") from exc
    return completed.stdout


def environment_metadata(engine: Engine) -> dict[str, object]:
    version_info = engine.dialect.server_version_info
    server_version = (
        ".".join(str(component) for component in version_info) if version_info else None
    )
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "dialect": engine.dialect.name,
        "server_version": server_version,
    }


def run_benchmark(
    session_factory: sessionmaker[Session],
    *,
    context: BenchmarkContext,
    concurrency: int,
    iterations: int,
    timeout_seconds: int,
) -> tuple[
    list[BenchmarkSample],
    list[BenchmarkFailureEvidence],
    dict[str, int],
    int,
    float,
]:
    samples: list[BenchmarkSample] = []
    failures: list[BenchmarkFailureEvidence] = []
    errors: dict[str, int] = {}
    timeouts = 0
    started = perf_counter()

    def record_failure(
        *,
        round_index: int,
        worker_index: int,
        error_code: str,
        timeout: bool = False,
    ) -> None:
        nonlocal timeouts
        errors[error_code] = errors.get(error_code, 0) + 1
        timeouts += int(timeout)
        failures.append(
            BenchmarkFailureEvidence(
                round_index=round_index,
                worker_index=worker_index,
                sample_index=round_index * concurrency + worker_index,
                error_code=error_code,
                timeout=timeout,
            )
        )

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for round_index in range(iterations):
            start_barrier = Barrier(
                concurrency,
                timeout=min(BARRIER_TIMEOUT_SECONDS, float(timeout_seconds)),
            )
            futures: dict[Future[BenchmarkSample], int] = {}
            for worker_index in range(concurrency):
                try:
                    future = executor.submit(
                        run_once,
                        session_factory,
                        context=context,
                        timeout_seconds=timeout_seconds,
                        round_index=round_index,
                        worker_index=worker_index,
                        sample_index=round_index * concurrency + worker_index,
                        start_barrier=start_barrier,
                    )
                except Exception as exc:
                    start_barrier.abort()
                    record_failure(
                        round_index=round_index,
                        worker_index=worker_index,
                        error_code=type(exc).__name__,
                    )
                    for unsubmitted_worker_index in range(worker_index + 1, concurrency):
                        record_failure(
                            round_index=round_index,
                            worker_index=unsubmitted_worker_index,
                            error_code="benchmark_submit_aborted",
                        )
                    break
                futures[future] = worker_index
            for future in as_completed(futures):
                worker_index = futures[future]
                try:
                    samples.append(future.result())
                except DashboardChartQueryError as exc:
                    timed_out = exc.code == "dataset_query_timeout"
                    record_failure(
                        round_index=round_index,
                        worker_index=worker_index,
                        error_code=exc.code,
                        timeout=timed_out,
                    )
                except BrokenBarrierError:
                    record_failure(
                        round_index=round_index,
                        worker_index=worker_index,
                        error_code="benchmark_start_barrier_broken",
                    )
                except Exception as exc:
                    record_failure(
                        round_index=round_index,
                        worker_index=worker_index,
                        error_code=type(exc).__name__,
                    )
    samples.sort(key=lambda sample: sample.sample_index)
    failures.sort(key=lambda failure: failure.sample_index)
    return samples, failures, errors, timeouts, perf_counter() - started


def run_once(
    session_factory: sessionmaker[Session],
    *,
    context: BenchmarkContext,
    timeout_seconds: int,
    round_index: int = -1,
    worker_index: int = -1,
    sample_index: int = -1,
    start_barrier: Barrier | None = None,
) -> BenchmarkSample:
    if start_barrier is not None:
        start_barrier.wait()
    started = perf_counter()
    truncated_results = 0
    evidence: list[BenchmarkResultEvidence] = []
    with session_factory() as session:
        for scenario in context.scenarios:
            scenario_started = perf_counter()
            result = execute_dashboard_chart_query(
                session,
                principal=scenario.principal,
                request=scenario.request,
                workspace_timezone="Asia/Hong_Kong",
                timeout_seconds=timeout_seconds,
            )
            client_duration_ms = (perf_counter() - scenario_started) * 1_000
            truncated_results += int(result.truncated)
            canonical_rows = (
                canonicalize_rows(result.rows)
                if scenario.name == "restricted_viewer_same_group"
                else ()
            )
            evidence.append(
                BenchmarkResultEvidence(
                    scenario_name=scenario.name,
                    principal_name=scenario.principal_name,
                    row_count=len(result.rows),
                    fingerprint=result_fingerprint(result),
                    truncated=result.truncated,
                    canonical_rows=canonical_rows,
                    canonical_row_fingerprint=(
                        canonical_rows_fingerprint(canonical_rows) if canonical_rows else None
                    ),
                    client_duration_ms=round(client_duration_ms, 3),
                    elapsed_ms=round(result.elapsed_ms, 3),
                )
            )
    return BenchmarkSample(
        sample_index=sample_index,
        duration_ms=(perf_counter() - started) * 1_000,
        truncated_results=truncated_results,
        results=tuple(evidence),
        round_index=round_index,
        worker_index=worker_index,
    )


def result_fingerprint(result: DashboardChartResult) -> str:
    payload = {
        "columns": [
            {
                "slot_key": column.slot_key,
                "query_alias": column.query_alias,
                "resource_kind": column.resource_kind,
                "aggregate": column.aggregate,
                "label": column.label,
                "data_type": column.data_type,
                "unit": column.unit,
            }
            for column in result.columns
        ],
        "rows": _canonical_value(result.rows),
        "dataset_version": result.dataset_version,
        "metric_version_ids": _normalized_opaque_ids("metric-version", result.metric_version_ids),
        "source_batch_ids": _normalized_opaque_ids("source-batch", result.source_batch_ids),
        "resolved_filters": [
            {
                "scope": evidence.scope,
                "field": f"resolved-filter-field-{index + 1}",
                "field_type": evidence.field_type,
                "semantic": evidence.semantic,
                "timezone": evidence.timezone,
                "start": _canonical_value(evidence.start),
                "end": _canonical_value(evidence.end),
            }
            for index, evidence in enumerate(result.resolved_filters)
        ],
        "truncated": result.truncated,
        "warning_codes": [warning.code for warning in result.warnings],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def canonicalize_rows(
    rows: Sequence[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    canonical = [cast(dict[str, object], _canonical_value(row)) for row in rows]
    canonical.sort(
        key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return tuple(canonical)


def canonical_rows_fingerprint(rows: Sequence[dict[str, object]]) -> str:
    serialized = json.dumps(
        canonicalize_rows(rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalized_opaque_ids(prefix: str, values: Sequence[UUID]) -> list[str]:
    return [f"{prefix}-{index + 1}" for index, _value in enumerate(values)]


def _canonical_value(value: object) -> object:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {str(key): _canonical_value(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        items = cast(Sequence[object], value)
        return [_canonical_value(item) for item in items]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def seed_dashboard_benchmark(
    session_factory: sessionmaker[Session],
    *,
    principal: QueryPrincipal,
    dataset_id: UUID,
    rows: int,
    fixture_dir: Path | None = None,
) -> BenchmarkContext:
    fixture = (
        validate_benchmark_fixture(fixture_dir, expected_rows=rows)
        if fixture_dir is not None
        else None
    )
    with session_factory.begin() as session:
        fields = {
            field.name: field
            for field in session.scalars(
                select(DatasetField).where(DatasetField.dataset_id == dataset_id)
            ).all()
        }
        category_field = fields["category"] if fixture is not None else fields["product_name"]
        product_field = fields["product_name"]
        region_field = fields["region_name"]
        rls_field = fields["region_key"] if fixture is not None else region_field
        measure_field = fields["gross_amount"] if fixture is not None else fields["amount"]
        rls_value = "R-NORTH" if fixture is not None else "Region 1"
        administrator_user = session.get(User, principal.user_id)
        if administrator_user is None:
            raise RuntimeError("Benchmark administrator user was not found")
        editor_user = User(
            workspace_id=principal.workspace_id,
            username="m3-benchmark-editor",
            display_name="M3 Benchmark Editor",
            password_hash="benchmark-not-for-login",
        )
        restricted_user = User(
            workspace_id=principal.workspace_id,
            username="m3-benchmark-restricted-viewer",
            display_name="M3 Benchmark Restricted Viewer",
            password_hash="benchmark-not-for-login",
        )
        session.add_all([editor_user, restricted_user])
        session.flush()

        dashboard = Dashboard(
            workspace_id=principal.workspace_id,
            owner_user_id=administrator_user.id,
            name="M3 chart benchmark",
            status="active",
        )
        session.add(dashboard)
        session.flush()
        version = DashboardVersion(
            dashboard_id=dashboard.id,
            version=1,
            status="active",
            created_by_user_id=administrator_user.id,
        )
        session.add(version)
        session.flush()
        page = DashboardPage(
            dashboard_version_id=version.id,
            page_id=uuid4(),
            title="Benchmark",
            ordinal=0,
        )
        session.add(page)
        session.flush()
        components = (
            (
                "full_kpi",
                "kpi",
                _chart_config(
                    dataset_id,
                    dimensions=[],
                    measures=[_measure(measure_field.id)],
                    query_limit=1,
                ),
            ),
            (
                "category_bar",
                "bar",
                _chart_config(
                    dataset_id,
                    dimensions=[_dimension(category_field.id, "category")],
                    measures=[_measure(measure_field.id)],
                    query_limit=500,
                ),
            ),
            (
                "category_region_stacked",
                "stacked_bar",
                _chart_config(
                    dataset_id,
                    dimensions=[_dimension(category_field.id, "category")],
                    series_dimension=_series_dimension(
                        region_field.id,
                        "region",
                        max_series=20,
                    ),
                    measures=[_measure(measure_field.id)],
                    component_filter=_text_filter(
                        rls_field.id,
                        rls_value,
                    ),
                    query_limit=500,
                ),
            ),
            (
                "month_trend",
                "line",
                _chart_config(
                    dataset_id,
                    dimensions=[_dimension(fields["sold_on"].id, "month", time_grain="month")],
                    measures=[_measure(measure_field.id)],
                    query_limit=500,
                ),
            ),
            (
                "top_2",
                "ranking_table",
                _chart_config(
                    dataset_id,
                    dimensions=[_dimension(product_field.id, "product")],
                    measures=[_measure(measure_field.id)],
                    sort=[_field_sort(measure_field.id, aggregate="sum")],
                    top_n=2,
                    query_limit=500,
                ),
            ),
            (
                "global_page_component_filters",
                "bar",
                _chart_config(
                    dataset_id,
                    dimensions=[_dimension(category_field.id, "category")],
                    measures=[_measure(measure_field.id)],
                    query_limit=500,
                ),
            ),
        )
        component_ids: dict[str, UUID] = {}
        for ordinal, (scenario_name, component_type, config) in enumerate(components):
            component_id = uuid4()
            component_ids[scenario_name] = component_id
            session.add(
                DashboardComponent(
                    dashboard_version_id=version.id,
                    component_id=component_id,
                    page_row_id=page.id,
                    component_type=component_type,
                    config_schema_version=1,
                    config=config,
                    ordinal=ordinal,
                )
            )
        session.add_all(
            [
                DashboardPermission(
                    dashboard_id=dashboard.id,
                    subject_type="user",
                    subject_id=user.id,
                    capability="view",
                    created_by_user_id=administrator_user.id,
                )
                for user in (editor_user, restricted_user)
            ]
        )

        all_rows_policy = RowPolicy(
            workspace_id=principal.workspace_id,
            dataset_id=dataset_id,
            name="M3 benchmark all rows",
            version=1,
            effect="allow",
            expression=_comparison_filter(measure_field.id, "gte", 0),
            status="active",
            created_by_user_id=administrator_user.id,
        )
        restricted_policy = RowPolicy(
            workspace_id=principal.workspace_id,
            dataset_id=dataset_id,
            name="M3 benchmark Region 1 rows",
            version=1,
            effect="allow",
            expression=_comparison_filter(rls_field.id, "eq", rls_value),
            status="active",
            created_by_user_id=administrator_user.id,
        )
        session.add_all([all_rows_policy, restricted_policy])
        session.flush()
        session.add_all(
            [
                RowPolicyAssignment(
                    row_policy_id=all_rows_policy.id,
                    user_id=administrator_user.id,
                ),
                RowPolicyAssignment(
                    row_policy_id=all_rows_policy.id,
                    user_id=editor_user.id,
                ),
                RowPolicyAssignment(
                    row_policy_id=restricted_policy.id,
                    user_id=restricted_user.id,
                ),
            ]
        )
        dashboard_id = dashboard.id
        dashboard_version_id = version.id
        page_id = page.page_id
        editor_user_id = editor_user.id
        restricted_user_id = restricted_user.id

    principals: dict[PrincipalName, QueryPrincipal] = {
        "administrator": QueryPrincipal(
            user_id=principal.user_id,
            workspace_id=principal.workspace_id,
            role_ids=principal.role_ids,
            permissions=principal.permissions | RUNTIME_PRINCIPAL_PERMISSIONS["administrator"],
            is_system_admin=principal.is_system_admin,
        ),
        "editor": QueryPrincipal(
            user_id=editor_user_id,
            workspace_id=principal.workspace_id,
            permissions=RUNTIME_PRINCIPAL_PERMISSIONS["editor"],
        ),
        "restricted_viewer": QueryPrincipal(
            user_id=restricted_user_id,
            workspace_id=principal.workspace_id,
            permissions=RUNTIME_PRINCIPAL_PERMISSIONS["restricted_viewer"],
        ),
    }
    scoped_runtime_filters = RuntimeChartFilterScopes(
        global_filter=_text_filter(rls_field.id, rls_value),
        page_filter=_text_filter(
            category_field.id,
            "Hardware" if fixture is not None else "Product 1",
        ),
        component_filter=_comparison_filter(measure_field.id, "gte", 0),
    )

    scenario_specs: tuple[tuple[str, PrincipalName, str, RuntimeChartFilterScopes | None], ...] = (
        ("full_kpi", "administrator", "full_kpi", None),
        ("category_bar", "administrator", "category_bar", None),
        (
            "category_region_stacked",
            "administrator",
            "category_region_stacked",
            None,
        ),
        ("month_trend", "editor", "month_trend", None),
        ("top_2", "editor", "top_2", None),
        (
            "global_page_component_filters",
            "editor",
            "global_page_component_filters",
            scoped_runtime_filters,
        ),
        (
            "restricted_viewer_same_group",
            "restricted_viewer",
            "category_bar",
            None,
        ),
    )
    return BenchmarkContext(
        scenarios=tuple(
            BenchmarkScenario(
                name=scenario_name,
                principal_name=principal_name,
                principal=principals[principal_name],
                request=DashboardChartQueryRequest(
                    dashboard_id=dashboard_id,
                    dashboard_version_id=dashboard_version_id,
                    page_id=page_id,
                    component_id=component_ids[component_name],
                    runtime_filters=runtime_filters,
                ),
            )
            for scenario_name, principal_name, component_name, runtime_filters in scenario_specs
        ),
        rls_expectation=(
            _fixture_rls_expectation(fixture)
            if fixture is not None
            else RlsExpectation(
                unrestricted_row_count=_expected_category_row_count(rows),
                restricted_row_count=_expected_restricted_category_row_count(rows),
                unrestricted_source_row_count=rows,
                restricted_source_row_count=len(range(1, rows, 100)),
            )
        ),
        fixture_provenance=_fixture_provenance(rows, fixture=fixture),
    )


def _expected_category_row_count(rows: int) -> int:
    return min(100, (rows + 6) // 7)


def _expected_restricted_category_row_count(rows: int) -> int:
    return len({(index // 7) % 100 for index in range(1, rows, 100)})


def _fixture_rls_expectation(fixture: BenchmarkFixture) -> RlsExpectation:
    products = {
        row["product_key"]: row["category"] for row in _csv_rows(fixture.root / "dim_product.csv")
    }
    facts = _csv_rows(fixture.root / "fact_sales.csv")

    def category(row: dict[str, str]) -> str | None:
        product_key = row["product_key"]
        return products.get(product_key) if product_key else None

    restricted = [row for row in facts if row["region_key"] == "R-NORTH"]
    restricted_amounts: dict[str | None, Decimal] = {}
    for row in restricted:
        row_category = category(row)
        restricted_amounts[row_category] = restricted_amounts.get(
            row_category, Decimal("0.00")
        ) + Decimal(row["gross_amount"])
    restricted_canonical_rows = canonicalize_rows(
        tuple(
            {"dimension": row_category, "value_1": str(amount)}
            for row_category, amount in restricted_amounts.items()
        )
    )
    return RlsExpectation(
        unrestricted_row_count=len({category(row) for row in facts}),
        restricted_row_count=len({category(row) for row in restricted}),
        unrestricted_source_row_count=len(facts),
        restricted_source_row_count=len(restricted),
        restricted_canonical_rows=restricted_canonical_rows,
        fixture_oracle_trusted=True,
    )


def _fixture_provenance(
    rows: int,
    *,
    fixture: BenchmarkFixture | None,
) -> dict[str, object]:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    principals_path = FIXTURE_ROOT / "principals.json"
    manifest = _read_json(manifest_path)
    principals = _read_json(principals_path)
    principal_permissions = {
        str(item["key"]): list(cast(list[object], item["permissions"]))
        for raw_item in cast(list[object], principals.get("principals", []))
        if (item := _object_dict(raw_item)) is not None
        and isinstance(item.get("key"), str)
        and isinstance(item.get("permissions"), list)
    }
    provenance: dict[str, object] = {
        "status": "pass" if fixture is not None else "partial",
        "fixture_version": manifest.get("fixture_version"),
        "fixture_manifest_sha256": _sha256(manifest_path),
        "fixture_manifest_path": "spikes/m3/quality/fixture/v2/manifest.json",
        "principal_contract_path": "spikes/m3/quality/fixture/v2/principals.json",
        "principal_permissions": principal_permissions,
        "runtime_principal_permissions": {
            name: sorted(permissions) for name, permissions in RUNTIME_PRINCIPAL_PERMISSIONS.items()
        },
        "permission_alignment": (
            "Runtime principals preserve the fixture-v2 capability separation and add only "
            "dashboards:view, which is required by the production read endpoint."
        ),
        "standard_fixture_consumed": fixture is not None,
        "benchmark_seed": "scripts/benchmark_m2_queries.py::seed_benchmark",
        "benchmark_rows": rows,
    }
    if fixture is None:
        provenance["reason"] = (
            "The benchmark uses the deterministic synthetic M2 star scale; it aligns the "
            "seven query shapes and three principal capabilities but does not load fixture-v2 "
            "row files or benchmark_manifest.json."
        )
    else:
        provenance.update(
            {
                "benchmark_profile": fixture.profile,
                "benchmark_manifest_sha256": fixture.manifest_sha256,
                "benchmark_fact_row_count": fixture.fact_row_count,
                "reason": (
                    "The benchmark loaded and verified the fixture-v2 deterministic performance "
                    "scale from all three CSV sources and schema.json."
                ),
            }
        )
    return provenance


def _read_json(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    mapping = _object_dict(value)
    if mapping is None:
        raise ValueError(f"Expected a JSON object: {path}")
    return mapping


def _object_dict(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _chart_config(
    dataset_id: UUID,
    *,
    dimensions: list[dict[str, object]],
    measures: list[dict[str, object]],
    query_limit: int,
    series_dimension: dict[str, object] | None = None,
    sort: list[dict[str, object]] | None = None,
    top_n: int | None = None,
    component_filter: dict[str, object] | None = None,
) -> dict[str, object]:
    query: dict[str, object] = {
        "dataset_id": str(dataset_id),
        "dimensions": dimensions,
        "measures": measures,
        "sort": [] if sort is None else sort,
        "query_limit": query_limit,
    }
    if series_dimension is not None:
        query["series_dimension"] = series_dimension
    if top_n is not None:
        query["top_n"] = top_n
    return {
        "schema_version": 1,
        "title": "Benchmark chart",
        "query": query,
        "component_filter": component_filter,
        "presentation": {},
    }


def _dimension(
    field_id: UUID,
    slot_key: str,
    *,
    time_grain: str | None = None,
) -> dict[str, object]:
    dimension: dict[str, object] = {
        "field_id": str(field_id),
        "slot_key": slot_key,
    }
    if time_grain is not None:
        dimension["time_grain"] = time_grain
    return dimension


def _series_dimension(
    field_id: UUID,
    slot_key: str,
    *,
    max_series: int,
) -> dict[str, object]:
    return {
        "field_id": str(field_id),
        "slot_key": slot_key,
        "max_series": max_series,
    }


def _field_sort(
    field_id: UUID,
    *,
    aggregate: str | None = None,
    direction: str = "desc",
) -> dict[str, object]:
    return {
        "kind": "field",
        "field_id": str(field_id),
        "aggregate": aggregate,
        "direction": direction,
    }


def _comparison_filter(
    field_id: UUID,
    operator: str,
    value: object,
) -> dict[str, object]:
    return {
        "kind": "comparison",
        "field_id": str(field_id),
        "operator": operator,
        "value": value,
    }


def _text_filter(field_id: UUID, value: str) -> dict[str, object]:
    return {
        "kind": "text",
        "field_id": str(field_id),
        "operator": "contains",
        "value": value,
    }


def _measure(field_id: UUID) -> dict[str, object]:
    return {
        "kind": "field",
        "field_id": str(field_id),
        "aggregate": "sum",
        "slot_key": "amount",
    }


if __name__ == "__main__":
    raise SystemExit(main())
