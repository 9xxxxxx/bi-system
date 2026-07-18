import csv
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from bi_system.dashboards.filters import resolve_scoped_filters
from bi_system.db.session import create_database_engine
from bi_system.modeling.compiler import QueryCompiler, ResolvedSource
from bi_system.modeling.expression import FilterExpression, LogicalPredicate
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
    and_,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import ColumnElement

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "spikes" / "m3" / "quality" / "fixture" / "v2"


@dataclass(frozen=True)
class PortableFilterContext:
    engine: Engine
    table: Table
    source: ResolvedSource
    field_ids: dict[str, UUID]


@pytest.fixture
def portable_filter_context(
    tmp_path: Path,
) -> Iterator[PortableFilterContext]:
    database_url = os.environ.get(
        "BI_DATABASE_URL",
        f"sqlite+pysqlite:///{(tmp_path / 'dashboard-filter.db').as_posix()}",
    )
    engine = create_database_engine(database_url)
    metadata = MetaData()
    table = Table(
        f"m3_filter_{uuid4().hex}",
        metadata,
        Column("sales_id", Integer, primary_key=True),
        Column("_active", Boolean, nullable=False),
        Column("sold_on", Date, nullable=False),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column("region_key", String(32), nullable=False),
        Column("category", String(64), nullable=False),
        Column("gross_amount", Numeric(12, 2), nullable=False),
    )
    field_ids = {
        "sold_on": uuid4(),
        "occurred_at": uuid4(),
        "region_key": uuid4(),
        "category": uuid4(),
    }
    source = ResolvedSource(
        source_id=uuid4(),
        table=table,
        fields={field_ids[name]: table.c[name] for name in field_ids},
    )
    try:
        table.create(engine)
        with engine.begin() as connection:
            connection.execute(table.insert(), _fixture_rows())
        yield PortableFilterContext(
            engine=engine,
            table=table,
            source=source,
            field_ids=field_ids,
        )
    finally:
        table.drop(engine, checkfirst=True)
        engine.dispose()


def test_scoped_filters_and_rls_execute_in_frozen_order_on_supported_databases(
    portable_filter_context: PortableFilterContext,
) -> None:
    context = portable_filter_context
    resolved = resolve_scoped_filters(
        {
            "kind": "absolute_date_range",
            "field_id": context.field_ids["sold_on"],
            "field_type": "date",
            "start": "2026-01-01",
            "end": "2026-02-01",
        },
        {
            "kind": "set",
            "field_id": context.field_ids["region_key"],
            "operator": "in",
            "values": ["R-NORTH", "R-SOUTH"],
        },
        {
            "kind": "comparison",
            "field_id": context.field_ids["category"],
            "operator": "eq",
            "value": "Hardware",
        },
        "Asia/Hong_Kong",
        now=datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert _filter_field_ids(resolved.filters) == [
        context.field_ids["sold_on"],
        context.field_ids["region_key"],
        context.field_ids["category"],
    ]
    row_ids = _execute_scoped_filters(
        context,
        resolved.filters,
        policy_predicate=context.table.c["region_key"] == "R-NORTH",
    )

    assert row_ids == [1, 2]


def test_hong_kong_workspace_day_uses_python_utc_boundaries_on_supported_databases(
    portable_filter_context: PortableFilterContext,
) -> None:
    context = portable_filter_context
    resolved = resolve_scoped_filters(
        {
            "kind": "relative_date",
            "field_id": context.field_ids["occurred_at"],
            "field_type": "datetime",
            "period": "today",
        },
        None,
        None,
        "Asia/Hong_Kong",
        now=datetime(2026, 1, 5, 8, tzinfo=UTC),
    )

    assert resolved.evidence[0].start == datetime(2026, 1, 4, 16, tzinfo=UTC)
    assert resolved.evidence[0].end == datetime(2026, 1, 5, 16, tzinfo=UTC)
    assert _execute_scoped_filters(context, resolved.filters) == [2, 3]


def test_new_york_dst_day_keeps_closed_open_boundary_on_supported_databases(
    portable_filter_context: PortableFilterContext,
) -> None:
    context = portable_filter_context
    resolved = resolve_scoped_filters(
        {
            "kind": "relative_date",
            "field_id": context.field_ids["occurred_at"],
            "field_type": "datetime",
            "period": "today",
        },
        None,
        None,
        "America/New_York",
        now=datetime(2026, 3, 8, 16, tzinfo=UTC),
    )

    assert resolved.evidence[0].start == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert resolved.evidence[0].end == datetime(2026, 3, 9, 4, tzinfo=UTC)
    assert _execute_scoped_filters(context, resolved.filters) == [1002, 1003]


def _execute_scoped_filters(
    context: PortableFilterContext,
    filters: tuple[FilterExpression, ...],
    *,
    policy_predicate: ColumnElement[bool] | None = None,
) -> list[int]:
    compiler = QueryCompiler(dialect_name=context.engine.dialect.name)
    conditions: list[ColumnElement[bool]] = [context.table.c["_active"].is_(True)]
    if policy_predicate is not None:
        conditions.append(policy_predicate)
    conditions.extend(compiler.compile_filter(item, context.source) for item in filters)
    statement = (
        select(context.table.c["sales_id"])
        .where(and_(*conditions))
        .order_by(context.table.c["sales_id"])
    )
    with context.engine.connect() as connection:
        return list(connection.execute(statement).scalars())


def _filter_field_ids(filters: tuple[FilterExpression, ...]) -> list[UUID]:
    result: list[UUID] = []
    for expression in filters:
        if isinstance(expression, LogicalPredicate):
            result.append(expression.predicates[0].field_id)
        else:
            result.append(expression.field_id)
    return result


def _fixture_rows() -> list[dict[str, Any]]:
    products = _product_categories()
    rows: list[dict[str, Any]] = []
    with (FIXTURE_ROOT / "fact_sales.csv").open(encoding="utf-8", newline="") as stream:
        for raw in csv.DictReader(stream):
            rows.append(
                {
                    "sales_id": int(raw["sales_id"]),
                    "_active": True,
                    "sold_on": date.fromisoformat(raw["sold_on"]),
                    "occurred_at": _utc_datetime(raw["occurred_at"]),
                    "region_key": raw["region_key"],
                    "category": products.get(raw["product_key"], "(Unmatched product)"),
                    "gross_amount": Decimal(raw["gross_amount"]),
                }
            )
    rows.extend(
        [
            _dst_row(1001, "2026-03-08T04:59:59Z"),
            _dst_row(1002, "2026-03-08T05:00:00Z"),
            _dst_row(1003, "2026-03-09T03:59:59Z"),
            _dst_row(1004, "2026-03-09T04:00:00Z"),
        ]
    )
    return rows


def _product_categories() -> dict[str, str]:
    with (FIXTURE_ROOT / "dim_product.csv").open(encoding="utf-8", newline="") as stream:
        return {row["product_key"]: row["category"] for row in csv.DictReader(stream)}


def _dst_row(sales_id: int, occurred_at: str) -> dict[str, Any]:
    return {
        "sales_id": sales_id,
        "_active": True,
        "sold_on": date(2026, 3, 8),
        "occurred_at": _utc_datetime(occurred_at),
        "region_key": "R-NORTH",
        "category": "Hardware",
        "gross_amount": Decimal("1.00"),
    }


def _utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
