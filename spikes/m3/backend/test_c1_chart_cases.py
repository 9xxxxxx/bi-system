from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bi_system.db.session import create_database_engine
from bi_system.modeling.compiler import QueryCompiler, ResolvedSource
from pydantic import BaseModel, ConfigDict, TypeAdapter
from sqlalchemy import Boolean, Column, Date, Integer, MetaData, Numeric, String, Table

from spikes.m3.backend.case_coverage import CASE_COVERAGE, CaseCoverage
from spikes.m3.backend.chart_query_compiler import (
    ChartCompilationError,
    ChartQueryCompiler,
    FieldMetadata,
    ResourceCatalog,
)
from spikes.m3.quality.fixture_tool import joined_sales

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class QualityChartCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    component_type: str
    golden_pointer: str


class QualityFilterCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    golden_pointer: str


class QualityChartCases(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_version: str
    cases: list[QualityChartCase]
    filter_cases: list[QualityFilterCase]


QUALITY_ROOT = Path(__file__).parents[1] / "quality" / "fixture" / "v1"
DATASET_ID = UUID("30000000-0000-0000-0000-000000000001")
FIELD_IDS = {
    "sales_id": UUID("30000000-0000-0000-0000-000000000002"),
    "order_id": UUID("30000000-0000-0000-0000-000000000003"),
    "sold_on": UUID("30000000-0000-0000-0000-000000000004"),
    "product_key": UUID("30000000-0000-0000-0000-000000000005"),
    "product_name": UUID("30000000-0000-0000-0000-000000000006"),
    "category": UUID("30000000-0000-0000-0000-000000000007"),
    "region_name": UUID("30000000-0000-0000-0000-000000000008"),
    "quantity": UUID("30000000-0000-0000-0000-000000000009"),
    "gross_amount": UUID("30000000-0000-0000-0000-000000000010"),
    "cost_amount": UUID("30000000-0000-0000-0000-000000000011"),
}
_GOLDEN_ADAPTER: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


def _quality_cases() -> QualityChartCases:
    return QualityChartCases.model_validate_json(
        (QUALITY_ROOT / "chart_cases.json").read_text(encoding="utf-8")
    )


def _golden_results() -> dict[str, JsonValue]:
    return _GOLDEN_ADAPTER.validate_json(
        (QUALITY_ROOT / "golden_results.json").read_text(encoding="utf-8")
    )


def _resolve_pointer(root: dict[str, JsonValue], pointer: str) -> JsonValue:
    current: JsonValue = root
    for part in pointer.removeprefix("/").split("/"):
        if not isinstance(current, dict) or part not in current:
            raise AssertionError(f"invalid C1 golden pointer: {pointer}")
        current = current[part]
    return current


def _measure_config(field_name: str, aggregate: str) -> dict[str, object]:
    return {
        "kind": "field",
        "field_id": FIELD_IDS[field_name],
        "aggregate": aggregate,
    }


def _config_for(coverage: CaseCoverage) -> dict[str, object]:
    measures = [
        _measure_config(measure.field_name, measure.aggregate.value)
        for measure in coverage.measures
    ]
    config: dict[str, object] = {
        "chart_type": coverage.component_type,
        "dataset_id": DATASET_ID,
    }
    if coverage.component_type == "kpi":
        config["value"] = measures[0]
        return config
    if coverage.component_type == "detail_table":
        config["columns"] = [FIELD_IDS[name] for name in coverage.dimensions]
        config["values"] = measures
        if coverage.sort_dimension:
            config["sort_field_id"] = FIELD_IDS[coverage.dimensions[0]]
        return config

    config["dimension_id"] = FIELD_IDS[coverage.dimensions[0]]
    if coverage.component_type in {"ranking_table", "pie", "donut"}:
        config["value"] = measures[0]
    else:
        config["values"] = measures
    if coverage.top_n is not None:
        config["top_n"] = coverage.top_n
    if coverage.sort_dimension:
        config["sort"] = {"by": "dimension", "direction": "asc"}
    if coverage.series_dimension is not None:
        config["series_dimension"] = {
            "field_id": FIELD_IDS[coverage.series_dimension],
            "max_series": coverage.max_series,
        }
    if coverage.time_grain is not None:
        config["time_grain"] = coverage.time_grain
    return config


def _fixture_source() -> tuple[Table, ResolvedSource, ResourceCatalog]:
    table = Table(
        f"m3_fixture_{uuid4().hex}",
        MetaData(),
        Column("_active", Boolean, nullable=False),
        Column("sales_id", Integer, nullable=False),
        Column("order_id", String, nullable=False),
        Column("sold_on", Date, nullable=False),
        Column("product_key", String),
        Column("product_name", String, nullable=False),
        Column("category", String, nullable=False),
        Column("region_name", String, nullable=False),
        Column("quantity", Integer, nullable=False),
        Column("gross_amount", Numeric(12, 2), nullable=False),
        Column("cost_amount", Numeric(12, 2), nullable=False),
    )
    fields = {
        FIELD_IDS["sales_id"]: table.c.sales_id,
        FIELD_IDS["order_id"]: table.c.order_id,
        FIELD_IDS["sold_on"]: table.c.sold_on,
        FIELD_IDS["product_key"]: table.c.product_key,
        FIELD_IDS["product_name"]: table.c.product_name,
        FIELD_IDS["category"]: table.c.category,
        FIELD_IDS["region_name"]: table.c.region_name,
        FIELD_IDS["quantity"]: table.c.quantity,
        FIELD_IDS["gross_amount"]: table.c.gross_amount,
        FIELD_IDS["cost_amount"]: table.c.cost_amount,
    }
    source = ResolvedSource(source_id=DATASET_ID, table=table, fields=fields)
    catalog = ResourceCatalog(
        dataset_id=DATASET_ID,
        fields={
            FIELD_IDS["sales_id"]: FieldMetadata(role="measure", data_type="integer"),
            FIELD_IDS["order_id"]: FieldMetadata(role="dimension", data_type="string"),
            FIELD_IDS["sold_on"]: FieldMetadata(role="dimension", data_type="date"),
            FIELD_IDS["product_key"]: FieldMetadata(role="dimension", data_type="string"),
            FIELD_IDS["product_name"]: FieldMetadata(role="dimension", data_type="string"),
            FIELD_IDS["category"]: FieldMetadata(role="dimension", data_type="string"),
            FIELD_IDS["region_name"]: FieldMetadata(role="dimension", data_type="string"),
            FIELD_IDS["quantity"]: FieldMetadata(role="measure", data_type="integer"),
            FIELD_IDS["gross_amount"]: FieldMetadata(role="measure", data_type="decimal"),
            FIELD_IDS["cost_amount"]: FieldMetadata(role="measure", data_type="decimal"),
        },
        metric_version_ids=frozenset(),
        field_cardinalities={
            FIELD_IDS["category"]: 3,
            FIELD_IDS["region_name"]: 4,
        },
    )
    return table, source, catalog


def _fixture_rows() -> list[dict[str, object]]:
    return [
        {
            "_active": True,
            "sales_id": row.sales_id,
            "order_id": row.order_id,
            "sold_on": row.sold_on,
            "product_key": row.product_key,
            "product_name": row.product_name,
            "category": row.category,
            "region_name": row.region_name,
            "quantity": row.quantity,
            "gross_amount": row.gross_amount,
            "cost_amount": row.cost_amount,
        }
        for row in joined_sales()
    ]


def _canonical(value: object) -> JsonValue:
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), "f")
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise AssertionError(f"unexpected query value type: {type(value).__name__}")


def _expected_projection(
    golden: JsonValue,
    projection: tuple[tuple[str, str], ...],
) -> list[dict[str, JsonValue]]:
    if not isinstance(golden, list):
        if projection != (("value_1", "$"),):
            raise AssertionError("scalar golden requires the KPI projection")
        return [{"value_1": golden}]
    result: list[dict[str, JsonValue]] = []
    for row in golden:
        if not isinstance(row, dict):
            raise AssertionError("golden result rows must be objects")
        result.append({output: row[key] for output, key in projection})
    return result


def test_c1_chart_cases_compile_or_return_the_declared_gap_and_match_golden() -> None:
    quality_cases = _quality_cases()
    golden_results = _golden_results()
    cases_by_id = {case.case_id: case for case in quality_cases.cases}
    assert set(cases_by_id) == {coverage.case_id for coverage in CASE_COVERAGE}
    assert quality_cases.fixture_version == "m3-star-v1"

    table, source, catalog = _fixture_source()
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), _fixture_rows())
        for coverage in CASE_COVERAGE:
            quality_case = cases_by_id[coverage.case_id]
            assert quality_case.component_type == coverage.component_type
            golden = _resolve_pointer(golden_results, quality_case.golden_pointer)
            config = _config_for(coverage)
            if coverage.disposition == "gap":
                with pytest.raises(ChartCompilationError) as captured:
                    ChartQueryCompiler().compile(config, catalog)
                assert captured.value.code == coverage.expected_gap_code, coverage.case_id
                continue

            chart_query = ChartQueryCompiler().compile(config, catalog)
            compiled = QueryCompiler(dialect_name="sqlite").compile_dataset_query(
                chart_query.request,
                source,
                metrics=(),
            )
            rows = connection.execute(compiled.statement).mappings().all()
            ChartQueryCompiler.validate_result_completeness(
                chart_query,
                row_count=len(rows),
                truncated=False,
            )
            if coverage.series_dimension is not None:
                assert chart_query.series_row_upper_bound == 12
            actual = [
                {
                    output: _canonical(row[output])
                    for output, _golden_key in coverage.golden_projection
                }
                for row in rows
            ]
            expected = _expected_projection(golden, coverage.golden_projection)
            assert actual == expected, coverage.case_id
    engine.dispose()


def test_series_dimension_top_n_has_a_stable_gap_code() -> None:
    _table, _source, catalog = _fixture_source()
    config: dict[str, object] = {
        "chart_type": "stacked_bar",
        "dataset_id": DATASET_ID,
        "dimension_id": FIELD_IDS["category"],
        "series_dimension": {
            "field_id": FIELD_IDS["region_name"],
            "max_series": 4,
        },
        "values": [_measure_config("gross_amount", "sum")],
        "top_n": 2,
    }

    with pytest.raises(ChartCompilationError) as captured:
        ChartQueryCompiler().compile(config, catalog)
    assert captured.value.code == "series_top_n_not_supported"


def test_series_dimension_requires_server_resolved_cardinality() -> None:
    _table, _source, catalog = _fixture_source()
    unresolved_catalog = ResourceCatalog(
        dataset_id=catalog.dataset_id,
        fields=catalog.fields,
        metric_version_ids=catalog.metric_version_ids,
    )
    config: dict[str, object] = {
        "chart_type": "stacked_bar",
        "dataset_id": DATASET_ID,
        "dimension_id": FIELD_IDS["category"],
        "series_dimension": {
            "field_id": FIELD_IDS["region_name"],
            "max_series": 4,
        },
        "values": [_measure_config("gross_amount", "sum")],
    }

    with pytest.raises(ChartCompilationError) as captured:
        ChartQueryCompiler().compile(config, unresolved_catalog)
    assert captured.value.code == "series_cardinality_not_resolved"
    assert captured.value.path == "dimension_id"


def test_series_query_fails_closed_when_complete_group_bound_exceeds_limit() -> None:
    _table, _source, catalog = _fixture_source()
    high_cardinality_catalog = ResourceCatalog(
        dataset_id=catalog.dataset_id,
        fields=catalog.fields,
        metric_version_ids=catalog.metric_version_ids,
        field_cardinalities={
            FIELD_IDS["category"]: 126,
            FIELD_IDS["region_name"]: 4,
        },
    )
    config: dict[str, object] = {
        "chart_type": "stacked_bar",
        "dataset_id": DATASET_ID,
        "dimension_id": FIELD_IDS["category"],
        "series_dimension": {
            "field_id": FIELD_IDS["region_name"],
            "max_series": 4,
        },
        "values": [_measure_config("gross_amount", "sum")],
    }

    with pytest.raises(ChartCompilationError) as captured:
        ChartQueryCompiler().compile(config, high_cardinality_catalog)
    assert captured.value.code == "series_result_limit_exceeded"
    assert captured.value.path == "query_limit"

    config["query_limit"] = 504
    compiled = ChartQueryCompiler().compile(config, high_cardinality_catalog)
    assert compiled.request.limit == 504
    assert compiled.series_row_upper_bound == 504


def test_series_query_rejects_truncated_or_cardinality_inconsistent_results() -> None:
    _table, _source, catalog = _fixture_source()
    config: dict[str, object] = {
        "chart_type": "stacked_bar",
        "dataset_id": DATASET_ID,
        "dimension_id": FIELD_IDS["category"],
        "series_dimension": {
            "field_id": FIELD_IDS["region_name"],
            "max_series": 4,
        },
        "values": [_measure_config("gross_amount", "sum")],
    }
    compiled = ChartQueryCompiler().compile(config, catalog)

    with pytest.raises(ChartCompilationError) as truncated:
        ChartQueryCompiler.validate_result_completeness(
            compiled,
            row_count=12,
            truncated=True,
        )
    assert truncated.value.code == "series_result_truncated"
    assert truncated.value.path == "result.truncated"

    with pytest.raises(ChartCompilationError) as stale:
        ChartQueryCompiler.validate_result_completeness(
            compiled,
            row_count=13,
            truncated=False,
        )
    assert stale.value.code == "series_cardinality_evidence_stale"
    assert stale.value.path == "result.rows"
