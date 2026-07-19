from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import tempfile
from collections.abc import Generator, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, cast
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
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Uuid,
    create_engine,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

BENCHMARK_FIXTURE_VERSION = "m3-star-v2"
BENCHMARK_FIXTURE_PROFILE = "deterministic_performance_scale"
BENCHMARK_FIXTURE_FILES = frozenset(
    {"dim_product.csv", "dim_region.csv", "fact_sales.csv", "schema.json"}
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TRUSTED_FIXTURE_ROOT = REPOSITORY_ROOT / "spikes" / "m3" / "quality" / "fixture" / "v2"
TRUSTED_FIXTURE_MANIFEST = TRUSTED_FIXTURE_ROOT / "manifest.json"
TRUSTED_BASE_FACT_ROW_COUNT = 14
FIXTURE_INSERT_BATCH_SIZE = 5_000
BENCHMARK_GENERATOR_CONTRACT = (
    "fixture_tool.generate_benchmark/v1: repeat the trusted checked-in 14-row fact fixture; "
    "set sales_id=offset+1 and order_id=B{cycle:06d}-{base_order_id}; "
    "preserve every other field"
)


@dataclass(frozen=True, slots=True)
class BenchmarkFixture:
    root: Path
    fixture_version: str
    profile: str
    fact_row_count: int
    manifest_sha256: str
    trusted_source_manifest_sha256: str
    generator_contract: str


@dataclass(frozen=True, slots=True)
class FixtureColumnSpec:
    name: str
    data_type: str
    nullable: bool
    precision: int | None = None
    scale: int | None = None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark governed M2 star-model queries")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument(
        "--database-url",
        help="Isolated PostgreSQL database URL; defaults to a temporary SQLite database",
    )
    args = parser.parse_args(argv)
    if min(args.rows, args.concurrency, args.iterations, args.timeout_seconds) < 1:
        parser.error("rows, concurrency, iterations, and timeout must be positive")
    if args.database_url and make_url(args.database_url).get_backend_name() != "postgresql":
        parser.error("database-url must use the PostgreSQL dialect")
    return args


def main() -> int:
    args = parse_args()
    with (
        tempfile.TemporaryDirectory(prefix="bi-m2-benchmark-") as temporary_directory,
        benchmark_database_engine(
            args.database_url,
            temporary_directory=Path(temporary_directory),
            pool_capacity=args.concurrency,
        ) as engine,
    ):
        dialect = engine.dialect.name
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

    completed = len(durations)
    output = {
        "dialect": dialect,
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


@contextmanager
def benchmark_database_engine(
    database_url: str | None,
    *,
    temporary_directory: Path,
    pool_capacity: int = 5,
) -> Generator[Engine]:
    if database_url is None:
        database_path = temporary_directory / "benchmark.db"
        engine = create_benchmark_engine(
            f"sqlite+pysqlite:///{database_path.as_posix()}",
            pool_capacity=pool_capacity,
        )
        try:
            yield engine
        finally:
            engine.dispose()
        return

    schema_name = f"bi_m2_benchmark_{uuid4().hex}"
    administration_engine = create_database_engine(database_url)
    schema_created = False
    try:
        with administration_engine.begin() as connection:
            connection.execute(CreateSchema(schema_name))
        schema_created = True

        benchmark_url = make_url(database_url).update_query_dict(
            {"options": f"-csearch_path={schema_name}"}
        )
        engine = create_benchmark_engine(
            benchmark_url.render_as_string(hide_password=False),
            pool_capacity=pool_capacity,
        )
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        if schema_created:
            with administration_engine.begin() as connection:
                connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))
        administration_engine.dispose()


def create_benchmark_engine(url: str, *, pool_capacity: int) -> Engine:
    dialect = make_url(url).get_backend_name()
    if dialect == "sqlite":
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_size=pool_capacity,
            max_overflow=0,
        )
    if dialect == "postgresql":
        return create_engine(url, pool_pre_ping=True, pool_size=pool_capacity, max_overflow=0)

    msg = f"Unsupported database dialect: {dialect}"
    raise ValueError(msg)


def validate_benchmark_fixture(
    fixture_dir: Path,
    *,
    expected_rows: int,
) -> BenchmarkFixture:
    root = fixture_dir.resolve()
    manifest_path = root / "benchmark_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Benchmark fixture manifest is missing: {manifest_path}")
    manifest = _read_object(manifest_path)
    fixture_version = manifest.get("fixture_version")
    profile = manifest.get("profile")
    fact_row_count = manifest.get("fact_row_count")
    if not isinstance(fixture_version, str):
        raise ValueError("Benchmark fixture version must be a string")
    if not isinstance(profile, str):
        raise ValueError("Benchmark fixture profile must be a string")
    if type(fact_row_count) is not int:
        raise ValueError("Benchmark fixture fact row count must be an integer")
    if fixture_version != BENCHMARK_FIXTURE_VERSION:
        raise ValueError(f"Unexpected benchmark fixture version: {fixture_version}")
    if profile != BENCHMARK_FIXTURE_PROFILE:
        raise ValueError(f"Unexpected benchmark fixture profile: {profile}")
    if fact_row_count != expected_rows:
        raise ValueError(
            f"Benchmark fixture row count {fact_row_count} does not match requested {expected_rows}"
        )
    raw_files = manifest.get("files")
    files = _object_dict(raw_files)
    if files is None or set(files) != set(BENCHMARK_FIXTURE_FILES):
        raise ValueError("Benchmark fixture manifest must pin exactly the four required data files")

    trusted_manifest = _read_object(TRUSTED_FIXTURE_MANIFEST)
    if trusted_manifest.get("fixture_version") != BENCHMARK_FIXTURE_VERSION:
        raise ValueError("Trusted fixture manifest version does not match the benchmark contract")
    trusted_files = _required_object(
        trusted_manifest.get("files"),
        "trusted fixture manifest files",
    )
    for filename in BENCHMARK_FIXTURE_FILES:
        if filename not in trusted_files:
            raise ValueError(f"Trusted fixture manifest does not pin {filename}")
        _validate_file_metadata(
            TRUSTED_FIXTURE_ROOT / filename,
            _required_object(trusted_files[filename], f"trusted metadata for {filename}"),
            label=f"trusted fixture {filename}",
        )

    for filename in sorted(BENCHMARK_FIXTURE_FILES):
        path = root / filename
        if not path.is_file():
            raise ValueError(f"Benchmark fixture file is missing: {filename}")
        _validate_file_metadata(
            path,
            _required_object(files[filename], f"benchmark metadata for {filename}"),
            label=f"benchmark fixture {filename}",
        )

    for filename in ("schema.json", "dim_product.csv", "dim_region.csv"):
        trusted_metadata = _required_object(
            trusted_files[filename],
            f"trusted metadata for {filename}",
        )
        if _sha256(root / filename) != trusted_metadata["sha256"]:
            raise ValueError(f"Benchmark {filename} does not match the trusted fixture")

    _validate_dimension_csv(root / "dim_product.csv", TRUSTED_FIXTURE_ROOT / "dim_product.csv")
    _validate_dimension_csv(root / "dim_region.csv", TRUSTED_FIXTURE_ROOT / "dim_region.csv")
    _validate_scaled_fact_rows(root / "fact_sales.csv", expected_rows=expected_rows)
    return BenchmarkFixture(
        root=root,
        fixture_version=fixture_version,
        profile=profile,
        fact_row_count=fact_row_count,
        manifest_sha256=_sha256(manifest_path),
        trusted_source_manifest_sha256=_sha256(TRUSTED_FIXTURE_MANIFEST),
        generator_contract=BENCHMARK_GENERATOR_CONTRACT,
    )


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
    fixture_dir: Path | None = None,
) -> tuple[QueryPrincipal, DatasetQueryRequest]:
    if fixture_dir is not None:
        fixture = validate_benchmark_fixture(fixture_dir, expected_rows=rows)
        return _seed_fixture_benchmark(
            engine,
            session_factory,
            fixture=fixture,
        )
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
            [
                ("region_id", "integer"),
                ("product_id", "integer"),
                ("amount", "decimal"),
                ("sold_on", "date"),
            ],
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
                    (sources[0], fact_columns[3], "sold_on", "Sold on", "dimension", "date"),
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


def _seed_fixture_benchmark(
    engine: Engine,
    session_factory: sessionmaker[Session],
    *,
    fixture: BenchmarkFixture,
) -> tuple[QueryPrincipal, DatasetQueryRequest]:
    Base.metadata.create_all(engine)
    schema = _read_object(fixture.root / "schema.json")
    source_definitions = _fixture_source_definitions(schema)
    workspace_id = uuid4()
    source_order = ("fact_sales", "dim_region", "dim_product")
    with session_factory.begin() as session:
        user = User(
            workspace_id=workspace_id,
            username="benchmark",
            display_name="M3 Fixture Benchmark",
            password_hash="benchmark-not-for-login",
        )
        session.add(user)
        session.flush()
        targets = {
            source_name: ImportTarget(
                workspace_id=workspace_id,
                name=f"M3 fixture {source_name}",
                physical_table_name=f"data_{uuid4().hex}",
                status="active",
            )
            for source_name in source_order
        }
        session.add_all(targets.values())
        session.flush()
        import_columns = {
            source_name: _add_fixture_columns(
                session,
                targets[source_name],
                source_definitions[source_name],
            )
            for source_name in source_order
        }
        model = SemanticModel(
            workspace_id=workspace_id,
            name="M3 fixture benchmark model",
            version=1,
            status="active",
            created_by_user_id=user.id,
        )
        session.add(model)
        session.flush()
        model_sources = {
            source_name: SemanticModelSource(
                semantic_model_id=model.id,
                target_id=targets[source_name].id,
                alias={
                    "fact_sales": "sales",
                    "dim_region": "region",
                    "dim_product": "product",
                }[source_name],
                source_role="fact" if source_name == "fact_sales" else "dimension",
                ordinal=ordinal,
            )
            for ordinal, source_name in enumerate(source_order)
        }
        session.add_all(model_sources.values())
        session.flush()
        joins = {
            dimension: SemanticModelJoin(
                semantic_model_id=model.id,
                left_source_id=model_sources["fact_sales"].id,
                right_source_id=model_sources[dimension].id,
                join_type="left",
                cardinality="many_to_one",
                ordinal=ordinal,
            )
            for ordinal, dimension in enumerate(("dim_region", "dim_product"))
        }
        session.add_all(joins.values())
        session.flush()
        session.add_all(
            [
                SemanticModelJoinKey(
                    semantic_model_join_id=joins["dim_region"].id,
                    left_column_id=import_columns["fact_sales"]["region_key"].id,
                    right_column_id=import_columns["dim_region"]["region_key"].id,
                    ordinal=0,
                ),
                SemanticModelJoinKey(
                    semantic_model_join_id=joins["dim_product"].id,
                    left_column_id=import_columns["fact_sales"]["product_key"].id,
                    right_column_id=import_columns["dim_product"]["product_key"].id,
                    ordinal=0,
                ),
            ]
        )
        dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=model.id,
            name="M3 fixture benchmark dataset",
            version=1,
            status="active",
            created_by_user_id=user.id,
        )
        session.add(dataset)
        session.flush()
        field_specs = (
            ("dim_product", "category", "category", "Category", "dimension", "string"),
            (
                "dim_product",
                "product_name",
                "product_name",
                "Product",
                "dimension",
                "string",
            ),
            ("dim_region", "region_key", "region_key", "Region key", "dimension", "string"),
            (
                "dim_region",
                "region_name",
                "region_name",
                "Region",
                "dimension",
                "string",
            ),
            (
                "fact_sales",
                "gross_amount",
                "gross_amount",
                "Gross amount",
                "measure",
                "decimal",
            ),
            ("fact_sales", "sold_on", "sold_on", "Sold on", "dimension", "date"),
        )
        fields = {
            name: DatasetField(
                dataset_id=dataset.id,
                model_source_id=model_sources[source_name].id,
                source_column_id=import_columns[source_name][column_name].id,
                name=name,
                label=label,
                field_kind="source",
                field_role=role,
                data_type=data_type,
                ordinal=ordinal,
            )
            for ordinal, (
                source_name,
                column_name,
                name,
                label,
                role,
                data_type,
            ) in enumerate(field_specs)
        }
        session.add_all(fields.values())
        session.flush()
        user_id = user.id
        dataset_id = dataset.id
        field_ids = {name: field.id for name, field in fields.items()}

    tables = _create_fixture_physical_tables(engine, targets, source_definitions)
    _load_fixture_rows(engine, tables, fixture)
    principal = QueryPrincipal(
        user_id=user_id,
        workspace_id=workspace_id,
        permissions=frozenset({"datasets:query"}),
    )
    request = DatasetQueryRequest.model_validate(
        {
            "dataset_id": dataset_id,
            "selections": [
                {"field_id": field_ids["region_name"], "output_name": "region"},
                {"field_id": field_ids["category"], "output_name": "category"},
                {
                    "field_id": field_ids["gross_amount"],
                    "output_name": "total_gross",
                    "aggregate": "sum",
                },
            ],
            "group_by": [field_ids["region_name"], field_ids["category"]],
            "limit": 500,
        }
    )
    return principal, request


def _add_fixture_columns(
    session: Session,
    target: ImportTarget,
    definitions: Sequence[FixtureColumnSpec],
) -> dict[str, ImportColumn]:
    columns = {
        definition.name: ImportColumn(
            target_id=target.id,
            source_name=definition.name,
            physical_name=definition.name,
            data_type=definition.data_type,
            nullable=definition.nullable,
            ordinal=ordinal,
        )
        for ordinal, definition in enumerate(definitions)
    }
    session.add_all(columns.values())
    session.flush()
    return columns


def _fixture_source_definitions(
    schema: dict[str, object],
) -> dict[str, tuple[FixtureColumnSpec, ...]]:
    sources = _object_dict(schema.get("sources"))
    if sources is None or set(sources) != {"fact_sales", "dim_region", "dim_product"}:
        raise ValueError("Benchmark fixture schema must define the three frozen sources")
    definitions: dict[str, tuple[FixtureColumnSpec, ...]] = {}
    for source_name, raw_source in sources.items():
        source = _required_object(raw_source, f"source {source_name}")
        fields = _required_object(source.get("fields"), f"fields for {source_name}")
        specs: list[FixtureColumnSpec] = []
        for field_name, raw_field in fields.items():
            field = _required_object(raw_field, f"field {source_name}.{field_name}")
            data_type = field.get("type")
            nullable = field.get("nullable")
            if not isinstance(data_type, str) or not isinstance(nullable, bool):
                raise ValueError(f"Invalid fixture field definition: {source_name}.{field_name}")
            precision = field.get("precision")
            scale = field.get("scale")
            specs.append(
                FixtureColumnSpec(
                    name=field_name,
                    data_type=data_type,
                    nullable=nullable,
                    precision=precision if isinstance(precision, int) else None,
                    scale=scale if isinstance(scale, int) else None,
                )
            )
        definitions[source_name] = tuple(specs)
    return definitions


def _create_fixture_physical_tables(
    engine: Engine,
    targets: dict[str, ImportTarget],
    definitions: dict[str, tuple[FixtureColumnSpec, ...]],
) -> dict[str, Table]:
    metadata = MetaData()
    tables = {
        source_name: Table(
            targets[source_name].physical_table_name,
            metadata,
            *system_columns(),
            *[
                Column(
                    definition.name,
                    _fixture_sql_type(definition),
                    nullable=definition.nullable,
                )
                for definition in definitions[source_name]
            ],
        )
        for source_name in ("fact_sales", "dim_region", "dim_product")
    }
    metadata.create_all(engine)
    return tables


def _fixture_sql_type(definition: FixtureColumnSpec) -> Any:
    if definition.data_type == "string":
        return String(255)
    if definition.data_type == "integer":
        return Integer()
    if definition.data_type == "decimal":
        return Numeric(definition.precision or 18, definition.scale or 2)
    if definition.data_type == "boolean":
        return Boolean()
    if definition.data_type == "date":
        return Date()
    if definition.data_type == "datetime":
        return DateTime(timezone=True)
    raise ValueError(f"Unsupported fixture field type: {definition.data_type}")


def _load_fixture_rows(
    engine: Engine,
    tables: dict[str, Table],
    fixture: BenchmarkFixture,
) -> None:
    schema = _fixture_source_definitions(_read_object(fixture.root / "schema.json"))
    batch_ids = {source_name: uuid4() for source_name in tables}
    with engine.begin() as connection:
        for source_name in ("dim_region", "dim_product", "fact_sales"):
            definitions = schema[source_name]
            rows = _iter_csv_rows(
                fixture.root / f"{source_name}.csv",
                expected_fieldnames=tuple(definition.name for definition in definitions),
                exact_field_order=False,
            )
            for batch in _fixture_insert_batches(
                rows,
                definitions=definitions,
                batch_id=batch_ids[source_name],
            ):
                connection.execute(tables[source_name].insert(), batch)


def _fixture_insert_batches(
    rows: Iterable[dict[str, str]],
    *,
    definitions: Sequence[FixtureColumnSpec],
    batch_id: UUID,
    batch_size: int = FIXTURE_INSERT_BATCH_SIZE,
) -> Generator[list[dict[str, object]]]:
    if batch_size < 1:
        raise ValueError("Fixture insert batch size must be positive")
    batch: list[dict[str, object]] = []
    for row_number, row in enumerate(rows, start=1):
        batch.append(
            system_row(
                batch_id,
                row_number,
                **{
                    definition.name: _fixture_value(row[definition.name], definition)
                    for definition in definitions
                },
            )
        )
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _fixture_value(value: str, definition: FixtureColumnSpec) -> object:
    if value == "":
        if definition.nullable:
            return None
        raise ValueError(f"Fixture field {definition.name} cannot be empty")
    if definition.data_type == "string":
        return value
    if definition.data_type == "integer":
        return int(value)
    if definition.data_type == "decimal":
        return Decimal(value)
    if definition.data_type == "boolean":
        if value not in {"true", "false"}:
            raise ValueError(f"Invalid boolean fixture value for {definition.name}")
        return value == "true"
    if definition.data_type == "date":
        return date.fromisoformat(value)
    if definition.data_type == "datetime":
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Unsupported fixture field type: {definition.data_type}")


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
            Column("sold_on", Date),
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
                        sold_on=date(2025, (index % 12) + 1, (index % 28) + 1),
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


def _read_object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    return _required_object(value, str(path))


def _object_dict(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _required_object(value: object, label: str) -> dict[str, object]:
    mapping = _object_dict(value)
    if mapping is None:
        raise ValueError(f"Expected JSON object for {label}")
    return mapping


def _validate_file_metadata(
    path: Path,
    metadata: dict[str, object],
    *,
    label: str,
) -> None:
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    expected_bytes = metadata.get("bytes")
    expected_sha256 = metadata.get("sha256")
    if type(expected_bytes) is not int or expected_bytes < 0:
        raise ValueError(f"{label} byte count metadata is invalid")
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ValueError(f"{label} SHA-256 metadata is invalid")
    if path.stat().st_size != expected_bytes:
        raise ValueError(f"{label} byte count mismatch")
    if _sha256(path) != expected_sha256:
        raise ValueError(f"{label} SHA-256 mismatch")


def _validate_dimension_csv(path: Path, trusted_path: Path) -> None:
    expected_fieldnames = _csv_fieldnames(trusted_path)
    for _row in _iter_csv_rows(path, expected_fieldnames=expected_fieldnames):
        pass


def _validate_scaled_fact_rows(path: Path, *, expected_rows: int) -> None:
    trusted_path = TRUSTED_FIXTURE_ROOT / "fact_sales.csv"
    trusted_fieldnames = _csv_fieldnames(trusted_path)
    trusted_rows = tuple(_iter_csv_rows(trusted_path, expected_fieldnames=trusted_fieldnames))
    if len(trusted_rows) != TRUSTED_BASE_FACT_ROW_COUNT:
        raise ValueError(
            "Trusted fact fixture does not contain the required "
            f"{TRUSTED_BASE_FACT_ROW_COUNT} base rows"
        )

    actual_count = 0
    for offset, row in enumerate(
        _iter_csv_rows(path, expected_fieldnames=trusted_fieldnames),
    ):
        actual_count = offset + 1
        source = trusted_rows[offset % TRUSTED_BASE_FACT_ROW_COUNT]
        cycle = offset // TRUSTED_BASE_FACT_ROW_COUNT + 1
        expected = {
            **source,
            "sales_id": str(offset + 1),
            "order_id": f"B{cycle:06d}-{source['order_id']}",
        }
        if row != expected:
            changed_fields = sorted(
                fieldname
                for fieldname in trusted_fieldnames
                if row[fieldname] != expected[fieldname]
            )
            raise ValueError(
                f"Benchmark fact row {actual_count} violates the deterministic scaling contract: "
                f"{', '.join(changed_fields)}"
            )
        if actual_count > expected_rows:
            raise ValueError(f"Benchmark fact CSV row count exceeds requested {expected_rows}")
    if actual_count != expected_rows:
        raise ValueError(
            f"Benchmark fact CSV row count {actual_count} does not match requested {expected_rows}"
        )


def _csv_fieldnames(path: Path) -> tuple[str, ...]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return _validated_csv_fieldnames(path, reader.fieldnames)


def _iter_csv_rows(
    path: Path,
    *,
    expected_fieldnames: Sequence[str] | None = None,
    exact_field_order: bool = True,
) -> Generator[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = _validated_csv_fieldnames(path, reader.fieldnames)
        if expected_fieldnames is not None:
            expected = tuple(expected_fieldnames)
            matches = (
                fieldnames == expected if exact_field_order else set(fieldnames) == set(expected)
            )
            if not matches:
                raise ValueError(f"CSV header does not match the fixture contract: {path}")
        for row_number, raw_row in enumerate(reader, start=1):
            if None in raw_row or any(value is None for value in raw_row.values()):
                raise ValueError(f"CSV row {row_number} has missing or extra fields: {path}")
            yield cast(dict[str, str], raw_row)


def _validated_csv_fieldnames(
    path: Path,
    fieldnames: Sequence[str] | None,
) -> tuple[str, ...]:
    if fieldnames is None or not fieldnames:
        raise ValueError(f"CSV header is missing: {path}")
    resolved = tuple(fieldnames)
    if any(not fieldname for fieldname in resolved) or len(set(resolved)) != len(resolved):
        raise ValueError(f"CSV header contains blank or duplicate fields: {path}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 3)


if __name__ == "__main__":
    raise SystemExit(main())
