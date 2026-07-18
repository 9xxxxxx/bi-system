from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from bi_system.db.session import create_database_engine
from bi_system.modeling.compiler import QueryCompiler, ResolvedSource
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table

from spikes.m3.backend.chart_query_compiler import (
    ChartCompilationError,
    ChartQueryCompiler,
    FieldMetadata,
    ResourceCatalog,
)


@pytest.fixture
def resources() -> tuple[ResourceCatalog, dict[str, UUID]]:
    ids = {
        "dataset": uuid4(),
        "city": uuid4(),
        "amount": uuid4(),
        "quantity": uuid4(),
        "metric": uuid4(),
    }
    return (
        ResourceCatalog(
            dataset_id=ids["dataset"],
            fields={
                ids["city"]: FieldMetadata(role="dimension", data_type="string"),
                ids["amount"]: FieldMetadata(role="measure", data_type="integer"),
                ids["quantity"]: FieldMetadata(role="measure", data_type="integer"),
            },
            metric_version_ids=frozenset({ids["metric"]}),
        ),
        ids,
    )


def field_value(ids: dict[str, UUID], field: str = "amount") -> dict[str, object]:
    return {"kind": "field", "field_id": ids[field], "aggregate": "sum"}


@pytest.mark.parametrize(
    ("chart_type", "expected_outputs"),
    [
        ("kpi", ("value_1",)),
        ("detail_table", ("column_1", "column_2")),
        ("ranking_table", ("dimension", "value_1")),
        ("bar", ("dimension", "value_1")),
        ("stacked_bar", ("dimension", "value_1", "value_2")),
        ("line", ("dimension", "value_1")),
        ("area", ("dimension", "value_1")),
        ("pie", ("dimension", "value_1")),
        ("donut", ("dimension", "value_1")),
    ],
)
def test_supported_chart_shapes_compile_to_m2_contract(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
    chart_type: str,
    expected_outputs: tuple[str, ...],
) -> None:
    catalog, ids = resources
    payload: dict[str, object] = {"chart_type": chart_type, "dataset_id": ids["dataset"]}
    if chart_type == "kpi":
        payload["value"] = field_value(ids)
    elif chart_type == "detail_table":
        payload["columns"] = [ids["city"], ids["amount"]]
    elif chart_type in {"ranking_table", "pie", "donut"}:
        payload["dimension_id"] = ids["city"]
        payload["value"] = field_value(ids)
    else:
        payload["dimension_id"] = ids["city"]
        payload["values"] = [field_value(ids)]
        if chart_type == "stacked_bar":
            payload["values"] = [field_value(ids), field_value(ids, "quantity")]

    compiled = ChartQueryCompiler().compile(payload, catalog)

    assert tuple(output.output_name for output in compiled.outputs) == expected_outputs
    assert (
        tuple(selection.output_name for selection in compiled.request.selections)
        + tuple(metric.output_name for metric in compiled.request.metrics)
        == expected_outputs
    )
    assert isinstance(compiled.request, BaseModel)


def test_grouped_top_n_filter_and_sort_execute_through_m2_compiler(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
) -> None:
    catalog, ids = resources
    payload: dict[str, object] = {
        "chart_type": "bar",
        "dataset_id": ids["dataset"],
        "dimension_id": ids["city"],
        "values": [field_value(ids)],
        "top_n": 2,
        "filter": {
            "kind": "comparison",
            "field_id": ids["amount"],
            "operator": "gt",
            "value": 5,
        },
    }
    chart_query = ChartQueryCompiler().compile(payload, catalog)
    table = Table(
        f"data_{uuid4().hex}",
        MetaData(),
        Column("_active", Boolean, nullable=False),
        Column("city", String),
        Column("amount", Integer),
        Column("quantity", Integer),
    )
    source = ResolvedSource(
        source_id=ids["dataset"],
        table=table,
        fields={
            ids["city"]: table.c.city,
            ids["amount"]: table.c.amount,
            ids["quantity"]: table.c.quantity,
        },
    )
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            [
                {"_active": True, "city": "A", "amount": 10, "quantity": 1},
                {"_active": True, "city": "A", "amount": 15, "quantity": 2},
                {"_active": True, "city": "B", "amount": 20, "quantity": 3},
                {"_active": True, "city": "C", "amount": 3, "quantity": 4},
                {"_active": False, "city": "D", "amount": 999, "quantity": 5},
            ],
        )
        compiled = QueryCompiler(dialect_name="sqlite").compile_dataset_query(
            chart_query.request,
            source,
            metrics=(),
        )
        rows = connection.execute(compiled.statement).mappings().all()
    engine.dispose()

    assert rows == [
        {"dimension": "A", "value_1": 25},
        {"dimension": "B", "value_1": 20},
    ]
    assert chart_query.request.limit == 2
    aggregate = chart_query.request.order_by[0].aggregate
    assert aggregate is not None and aggregate.value == "sum"


def test_metric_version_is_selected_but_metric_top_n_is_explicitly_unsupported(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
) -> None:
    catalog, ids = resources
    kpi = ChartQueryCompiler().compile(
        {
            "chart_type": "kpi",
            "dataset_id": ids["dataset"],
            "value": {"kind": "metric", "metric_version_id": ids["metric"]},
        },
        catalog,
    )
    assert kpi.request.metrics[0].metric_id == ids["metric"]

    with pytest.raises(ChartCompilationError) as captured:
        ChartQueryCompiler().compile(
            {
                "chart_type": "ranking_table",
                "dataset_id": ids["dataset"],
                "dimension_id": ids["city"],
                "value": {"kind": "metric", "metric_version_id": ids["metric"]},
            },
            catalog,
        )
    assert captured.value.code == "metric_sort_not_supported"


@pytest.mark.parametrize("top_n", [1, 100])
def test_top_n_boundaries_are_accepted(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
    top_n: int,
) -> None:
    catalog, ids = resources
    compiled = ChartQueryCompiler().compile(
        {
            "chart_type": "ranking_table",
            "dataset_id": ids["dataset"],
            "dimension_id": ids["city"],
            "value": field_value(ids),
            "top_n": top_n,
        },
        catalog,
    )
    assert compiled.request.limit == top_n


@pytest.mark.parametrize("top_n", [0, 101])
def test_top_n_outside_boundaries_is_rejected(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
    top_n: int,
) -> None:
    catalog, ids = resources
    with pytest.raises(ChartCompilationError) as captured:
        ChartQueryCompiler().compile(
            {
                "chart_type": "ranking_table",
                "dataset_id": ids["dataset"],
                "dimension_id": ids["city"],
                "value": field_value(ids),
                "top_n": top_n,
            },
            catalog,
        )
    assert captured.value.code == "chart_config_invalid"
    assert captured.value.path is not None and captured.value.path.endswith("top_n")


def test_top_n_requires_descending_value_sort(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
) -> None:
    catalog, ids = resources
    with pytest.raises(ChartCompilationError) as captured:
        ChartQueryCompiler().compile(
            {
                "chart_type": "bar",
                "dataset_id": ids["dataset"],
                "dimension_id": ids["city"],
                "values": [field_value(ids)],
                "top_n": 10,
                "sort": {"by": "value", "direction": "asc"},
            },
            catalog,
        )
    assert captured.value.code == "top_n_requires_descending_sort"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"dimension_id": "unknown"}, "chart_config_invalid"),
        ({"dimension_id": None}, "chart_config_invalid"),
    ],
)
def test_invalid_slot_values_are_rejected(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
    mutation: dict[str, object],
    expected_code: str,
) -> None:
    catalog, ids = resources
    payload: dict[str, object] = {
        "chart_type": "bar",
        "dataset_id": ids["dataset"],
        "dimension_id": ids["city"],
        "values": [field_value(ids)],
        **mutation,
    }
    with pytest.raises(ChartCompilationError) as captured:
        ChartQueryCompiler().compile(payload, catalog)
    assert captured.value.code == expected_code


def test_unknown_references_and_invalid_aggregate_are_rejected(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
) -> None:
    catalog, ids = resources
    cases: list[tuple[dict[str, object], str]] = [
        (
            {
                "chart_type": "bar",
                "dataset_id": ids["dataset"],
                "dimension_id": uuid4(),
                "values": [field_value(ids)],
            },
            "field_not_resolved",
        ),
        (
            {
                "chart_type": "kpi",
                "dataset_id": ids["dataset"],
                "value": {"kind": "metric", "metric_version_id": uuid4()},
            },
            "metric_version_not_resolved",
        ),
        (
            {
                "chart_type": "kpi",
                "dataset_id": ids["dataset"],
                "value": {"kind": "field", "field_id": ids["city"], "aggregate": "sum"},
            },
            "invalid_aggregate_type",
        ),
    ]
    for payload, expected_code in cases:
        with pytest.raises(ChartCompilationError) as captured:
            ChartQueryCompiler().compile(payload, catalog)
        assert captured.value.code == expected_code


@pytest.mark.parametrize("forbidden_key", ["raw_sql", "table_name", "column_name", "function"])
def test_physical_names_sql_and_arbitrary_functions_are_rejected(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
    forbidden_key: str,
) -> None:
    catalog, ids = resources
    payload: dict[str, object] = {
        "chart_type": "kpi",
        "dataset_id": ids["dataset"],
        "value": field_value(ids),
        forbidden_key: "sales; DROP TABLE users --",
    }
    with pytest.raises(ChartCompilationError) as captured:
        ChartQueryCompiler().compile(payload, catalog)
    assert captured.value.code == "chart_config_invalid"


def test_filter_injection_remains_a_bound_parameter_in_m2_compiler(
    resources: tuple[ResourceCatalog, dict[str, UUID]],
) -> None:
    catalog, ids = resources
    injection = "x' OR 1=1 --"
    chart_query = ChartQueryCompiler().compile(
        {
            "chart_type": "detail_table",
            "dataset_id": ids["dataset"],
            "columns": [ids["city"]],
            "filter": {
                "kind": "comparison",
                "field_id": ids["city"],
                "operator": "eq",
                "value": injection,
            },
        },
        catalog,
    )
    table = Table(
        "governed_source",
        MetaData(),
        Column("_active", Boolean, nullable=False),
        Column("city", String),
        Column("amount", Integer),
        Column("quantity", Integer),
    )
    source = ResolvedSource(
        source_id=ids["dataset"],
        table=table,
        fields={
            ids["city"]: table.c.city,
            ids["amount"]: table.c.amount,
            ids["quantity"]: table.c.quantity,
        },
    )
    statement = (
        QueryCompiler(dialect_name="sqlite")
        .compile_dataset_query(
            chart_query.request,
            source,
            metrics=(),
        )
        .statement
    )
    sql = str(statement.compile())
    parameters = statement.compile().params

    assert injection not in sql
    assert injection in parameters.values()
    assert "_active" in sql
