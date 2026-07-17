from __future__ import annotations

import argparse
import json
import math
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from bi_system.db.base import Base
from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    SemanticModel,
    SemanticModelJoin,
    SemanticModelJoinKey,
    SemanticModelSource,
    User,
)
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from bi_system.modeling.contracts import DatasetQueryRequest
from bi_system.modeling.query_service import execute_dataset_query
from sqlalchemy import Boolean, Column, Integer, MetaData, Numeric, String, Table, Uuid
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark governed M2 star-model queries")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    args = parser.parse_args()
    if min(args.rows, args.concurrency, args.iterations, args.timeout_seconds) < 1:
        parser.error("rows, concurrency, iterations, and timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="bi-m2-benchmark-") as temporary_directory:
        database_path = Path(temporary_directory) / "benchmark.db"
        engine = create_database_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
        try:
            session_factory = create_session_factory(engine)
            principal, request = seed_benchmark(
                engine,
                session_factory,
                rows=args.rows,
            )
            run_once(
                session_factory,
                principal=principal,
                request=request,
                timeout_seconds=args.timeout_seconds,
            )
            durations, errors, wall_seconds = run_benchmark(
                session_factory,
                principal=principal,
                request=request,
                concurrency=args.concurrency,
                iterations=args.iterations,
                timeout_seconds=args.timeout_seconds,
            )
        finally:
            engine.dispose()

    completed = len(durations)
    output = {
        "rows": args.rows,
        "concurrency": args.concurrency,
        "iterations": args.iterations,
        "requests": args.concurrency * args.iterations,
        "completed": completed,
        "errors": errors,
        "error_count": sum(errors.values()),
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": percentile(durations, 0.95),
        "throughput_rps": round(completed / wall_seconds, 3) if wall_seconds else 0,
        "wall_seconds": round(wall_seconds, 3),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def run_benchmark(
    session_factory: sessionmaker[Session],
    *,
    principal: QueryPrincipal,
    request: DatasetQueryRequest,
    concurrency: int,
    iterations: int,
    timeout_seconds: int,
) -> tuple[list[float], dict[str, int], float]:
    durations: list[float] = []
    errors: dict[str, int] = {}
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                run_once,
                session_factory,
                principal=principal,
                request=request,
                timeout_seconds=timeout_seconds,
            )
            for _ in range(concurrency * iterations)
        ]
        for future in as_completed(futures):
            try:
                durations.append(future.result())
            except Exception as exc:
                key = type(exc).__name__
                errors[key] = errors.get(key, 0) + 1
    return durations, errors, perf_counter() - started


def run_once(
    session_factory: sessionmaker[Session],
    *,
    principal: QueryPrincipal,
    request: DatasetQueryRequest,
    timeout_seconds: int,
) -> float:
    started = perf_counter()
    with session_factory() as session:
        execute_dataset_query(
            session,
            principal=principal,
            request=request,
            timeout_seconds=timeout_seconds,
        )
    return (perf_counter() - started) * 1_000


def seed_benchmark(
    engine: Engine,
    session_factory: sessionmaker[Session],
    *,
    rows: int,
) -> tuple[QueryPrincipal, DatasetQueryRequest]:
    Base.metadata.create_all(engine)
    workspace_id = uuid4()
    with session_factory.begin() as session:
        user = User(
            workspace_id=workspace_id,
            username="benchmark",
            display_name="M2 Benchmark",
            password_hash="benchmark-not-for-login",
        )
        session.add(user)
        session.flush()
        targets = [
            ImportTarget(
                workspace_id=workspace_id,
                name=name,
                physical_table_name=f"data_{uuid4().hex}",
                status="active",
            )
            for name in ("Benchmark fact", "Region dimension", "Product dimension")
        ]
        session.add_all(targets)
        session.flush()
        fact_columns = add_columns(
            session,
            targets[0],
            [("region_id", "integer"), ("product_id", "integer"), ("amount", "decimal")],
        )
        region_columns = add_columns(
            session,
            targets[1],
            [("region_id", "integer"), ("region_name", "string")],
        )
        product_columns = add_columns(
            session,
            targets[2],
            [("product_id", "integer"), ("product_name", "string")],
        )
        model = SemanticModel(
            workspace_id=workspace_id,
            name="Benchmark star model",
            version=1,
            status="active",
            created_by_user_id=user.id,
        )
        session.add(model)
        session.flush()
        sources = [
            SemanticModelSource(
                semantic_model_id=model.id,
                target_id=target.id,
                alias=alias,
                source_role=role,
                ordinal=ordinal,
            )
            for ordinal, (target, alias, role) in enumerate(
                zip(
                    targets,
                    ("sales", "region", "product"),
                    ("fact", "dimension", "dimension"),
                    strict=True,
                )
            )
        ]
        session.add_all(sources)
        session.flush()
        joins = [
            SemanticModelJoin(
                semantic_model_id=model.id,
                left_source_id=sources[0].id,
                right_source_id=sources[index].id,
                join_type="left",
                cardinality="many_to_one",
                ordinal=index - 1,
            )
            for index in (1, 2)
        ]
        session.add_all(joins)
        session.flush()
        session.add_all(
            [
                SemanticModelJoinKey(
                    semantic_model_join_id=joins[0].id,
                    left_column_id=fact_columns[0].id,
                    right_column_id=region_columns[0].id,
                    ordinal=0,
                ),
                SemanticModelJoinKey(
                    semantic_model_join_id=joins[1].id,
                    left_column_id=fact_columns[1].id,
                    right_column_id=product_columns[0].id,
                    ordinal=0,
                ),
            ]
        )
        dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=model.id,
            name="Benchmark dataset",
            version=1,
            status="active",
            created_by_user_id=user.id,
        )
        session.add(dataset)
        session.flush()
        fields = [
            DatasetField(
                dataset_id=dataset.id,
                model_source_id=source.id,
                source_column_id=column.id,
                name=name,
                label=label,
                field_kind="source",
                field_role=role,
                data_type=data_type,
                ordinal=ordinal,
            )
            for ordinal, (source, column, name, label, role, data_type) in enumerate(
                [
                    (sources[1], region_columns[1], "region_name", "Region", "dimension", "string"),
                    (
                        sources[2],
                        product_columns[1],
                        "product_name",
                        "Product",
                        "dimension",
                        "string",
                    ),
                    (sources[0], fact_columns[2], "amount", "Amount", "measure", "decimal"),
                ]
            )
        ]
        session.add_all(fields)
        session.flush()
        user_id = user.id
        dataset_id = dataset.id
        field_ids = [field.id for field in fields]

    tables = create_physical_tables(engine, targets)
    seed_physical_rows(engine, tables, rows=rows)
    principal = QueryPrincipal(
        user_id=user_id,
        workspace_id=workspace_id,
        permissions=frozenset({"datasets:query"}),
    )
    request = DatasetQueryRequest.model_validate(
        {
            "dataset_id": dataset_id,
            "selections": [
                {"field_id": field_ids[0], "output_name": "region"},
                {"field_id": field_ids[1], "output_name": "product"},
                {"field_id": field_ids[2], "output_name": "total_amount", "aggregate": "sum"},
            ],
            "group_by": field_ids[:2],
            "limit": 500,
        }
    )
    return principal, request


def add_columns(
    session: Session,
    target: ImportTarget,
    definitions: list[tuple[str, str]],
) -> list[ImportColumn]:
    columns = [
        ImportColumn(
            target_id=target.id,
            source_name=name,
            physical_name=name,
            data_type=data_type,
            nullable=False,
            ordinal=ordinal,
        )
        for ordinal, (name, data_type) in enumerate(definitions)
    ]
    session.add_all(columns)
    session.flush()
    return columns


def create_physical_tables(engine: Engine, targets: list[ImportTarget]) -> list[Table]:
    metadata = MetaData()
    tables = [
        Table(
            targets[0].physical_table_name,
            metadata,
            *system_columns(),
            Column("region_id", Integer),
            Column("product_id", Integer),
            Column("amount", Numeric(18, 2)),
        ),
        Table(
            targets[1].physical_table_name,
            metadata,
            *system_columns(),
            Column("region_id", Integer),
            Column("region_name", String(64)),
        ),
        Table(
            targets[2].physical_table_name,
            metadata,
            *system_columns(),
            Column("product_id", Integer),
            Column("product_name", String(64)),
        ),
    ]
    metadata.create_all(engine)
    return tables


def system_columns() -> list[Column[Any]]:
    return [
        Column("_row_id", Uuid(as_uuid=True), primary_key=True),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_row_number", Integer, nullable=False),
        Column("_active", Boolean, nullable=False),
    ]


def seed_physical_rows(engine: Engine, tables: list[Table], *, rows: int) -> None:
    batch_ids = [uuid4(), uuid4(), uuid4()]
    with engine.begin() as connection:
        connection.execute(
            tables[1].insert(),
            [
                system_row(batch_ids[1], index, region_id=index, region_name=f"Region {index}")
                for index in range(100)
            ],
        )
        connection.execute(
            tables[2].insert(),
            [
                system_row(batch_ids[2], index, product_id=index, product_name=f"Product {index}")
                for index in range(100)
            ],
        )
        for start in range(0, rows, 5_000):
            connection.execute(
                tables[0].insert(),
                [
                    system_row(
                        batch_ids[0],
                        index,
                        region_id=index % 100,
                        product_id=(index // 7) % 100,
                        amount=(index % 10_000) / 100,
                    )
                    for index in range(start, min(start + 5_000, rows))
                ],
            )


def system_row(batch_id: UUID, row_number: int, **values: Any) -> dict[str, Any]:
    return {
        "_row_id": uuid4(),
        "_batch_id": batch_id,
        "_row_number": row_number,
        "_active": True,
        **values,
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 3)


if __name__ == "__main__":
    raise SystemExit(main())
