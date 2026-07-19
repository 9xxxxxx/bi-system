from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from benchmark_m2_queries import (
    benchmark_database_engine,
    percentile,
    seed_benchmark,
)
from bi_system.dashboards.chart_contracts import (
    DashboardChartQueryRequest,
    RuntimeChartFilterScopes,
)
from bi_system.dashboards.chart_query import (
    DashboardChartQueryError,
    execute_dashboard_chart_query,
)
from bi_system.db.models import (
    Dashboard,
    DashboardComponent,
    DashboardPage,
    DashboardVersion,
    DatasetField,
)
from bi_system.db.session import create_session_factory
from bi_system.identity import QueryPrincipal
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class BenchmarkContext:
    principal: QueryPrincipal
    requests: tuple[DashboardChartQueryRequest, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    duration_ms: float
    truncated_results: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark governed M3 dashboard chart queries")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--database-url")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if min(args.rows, args.concurrency, args.iterations, args.timeout_seconds) < 1:
        parser.error("rows, concurrency, iterations, and timeout must be positive")
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
        )
        context = seed_dashboard_benchmark(
            session_factory,
            principal=principal,
            dataset_id=dataset_request.dataset_id,
        )
        run_once(
            session_factory,
            context=context,
            timeout_seconds=args.timeout_seconds,
        )
        samples, errors, timeouts, wall_seconds = run_benchmark(
            session_factory,
            context=context,
            concurrency=args.concurrency,
            iterations=args.iterations,
            timeout_seconds=args.timeout_seconds,
        )
        dialect = engine.dialect.name

    durations = [sample.duration_ms for sample in samples]
    completed = len(samples)
    output = {
        "dialect": dialect,
        "rows": args.rows,
        "concurrency": args.concurrency,
        "iterations": args.iterations,
        "requests": args.concurrency * args.iterations,
        "queries_per_request": len(context.requests),
        "completed": completed,
        "errors": errors,
        "error_count": sum(errors.values()),
        "timeouts": timeouts,
        "truncated_results": sum(sample.truncated_results for sample in samples),
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": percentile(durations, 0.95),
        "throughput_rps": round(completed / wall_seconds, 3) if wall_seconds else 0,
        "wall_seconds": round(wall_seconds, 3),
    }
    serialized = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if not errors else 1


def run_benchmark(
    session_factory: sessionmaker[Session],
    *,
    context: BenchmarkContext,
    concurrency: int,
    iterations: int,
    timeout_seconds: int,
) -> tuple[list[BenchmarkSample], dict[str, int], int, float]:
    samples: list[BenchmarkSample] = []
    errors: dict[str, int] = {}
    timeouts = 0
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                run_once,
                session_factory,
                context=context,
                timeout_seconds=timeout_seconds,
            )
            for _ in range(concurrency * iterations)
        ]
        for future in as_completed(futures):
            try:
                samples.append(future.result())
            except DashboardChartQueryError as exc:
                errors[exc.code] = errors.get(exc.code, 0) + 1
                if exc.code == "dataset_query_timeout":
                    timeouts += 1
            except Exception as exc:
                name = type(exc).__name__
                errors[name] = errors.get(name, 0) + 1
    return samples, errors, timeouts, perf_counter() - started


def run_once(
    session_factory: sessionmaker[Session],
    *,
    context: BenchmarkContext,
    timeout_seconds: int,
) -> BenchmarkSample:
    started = perf_counter()
    truncated_results = 0
    with session_factory() as session:
        for request in context.requests:
            result = execute_dashboard_chart_query(
                session,
                principal=context.principal,
                request=request,
                workspace_timezone="Asia/Hong_Kong",
                timeout_seconds=timeout_seconds,
            )
            truncated_results += int(result.truncated)
    return BenchmarkSample(
        duration_ms=(perf_counter() - started) * 1_000,
        truncated_results=truncated_results,
    )


def seed_dashboard_benchmark(
    session_factory: sessionmaker[Session],
    *,
    principal: QueryPrincipal,
    dataset_id: UUID,
) -> BenchmarkContext:
    with session_factory.begin() as session:
        fields = {
            field.name: field
            for field in session.scalars(
                select(DatasetField).where(DatasetField.dataset_id == dataset_id)
            ).all()
        }
        dashboard = Dashboard(
            workspace_id=principal.workspace_id,
            owner_user_id=principal.user_id,
            name="M3 chart benchmark",
            status="active",
        )
        session.add(dashboard)
        session.flush()
        version = DashboardVersion(
            dashboard_id=dashboard.id,
            version=1,
            status="active",
            created_by_user_id=principal.user_id,
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
                "kpi",
                _chart_config(
                    dataset_id,
                    dimensions=[],
                    measures=[_measure(fields["amount"].id)],
                    query_limit=1,
                ),
            ),
            (
                "bar",
                _chart_config(
                    dataset_id,
                    dimensions=[_dimension(fields["region_name"].id, "region")],
                    measures=[_measure(fields["amount"].id)],
                    query_limit=500,
                ),
            ),
            (
                "ranking_table",
                _chart_config(
                    dataset_id,
                    dimensions=[_dimension(fields["product_name"].id, "product")],
                    measures=[_measure(fields["amount"].id)],
                    top_n=10,
                    query_limit=500,
                ),
            ),
        )
        component_ids: list[UUID] = []
        for ordinal, (component_type, config) in enumerate(components):
            component_id = uuid4()
            component_ids.append(component_id)
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
        dashboard_id = dashboard.id
        dashboard_version_id = version.id
        page_id = page.page_id

    governed_principal = QueryPrincipal(
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        permissions=frozenset({"dashboards:view", "datasets:query"}),
    )
    runtime_filters = RuntimeChartFilterScopes(
        global_filter={
            "kind": "text",
            "field_id": fields["region_name"].id,
            "operator": "contains",
            "value": "Region",
        }
    )
    return BenchmarkContext(
        principal=governed_principal,
        requests=tuple(
            DashboardChartQueryRequest(
                dashboard_id=dashboard_id,
                dashboard_version_id=dashboard_version_id,
                page_id=page_id,
                component_id=component_id,
                runtime_filters=runtime_filters,
            )
            for component_id in component_ids
        ),
    )


def _chart_config(
    dataset_id: UUID,
    *,
    dimensions: list[dict[str, object]],
    measures: list[dict[str, object]],
    query_limit: int,
    top_n: int | None = None,
) -> dict[str, object]:
    query: dict[str, object] = {
        "dataset_id": str(dataset_id),
        "dimensions": dimensions,
        "measures": measures,
        "sort": [],
        "query_limit": query_limit,
    }
    if top_n is not None:
        query["top_n"] = top_n
    return {
        "schema_version": 1,
        "title": "Benchmark chart",
        "query": query,
        "presentation": {},
    }


def _dimension(field_id: UUID, slot_key: str) -> dict[str, object]:
    return {"field_id": str(field_id), "slot_key": slot_key}


def _measure(field_id: UUID) -> dict[str, object]:
    return {
        "kind": "field",
        "field_id": str(field_id),
        "aggregate": "sum",
        "slot_key": "amount",
    }


if __name__ == "__main__":
    raise SystemExit(main())
