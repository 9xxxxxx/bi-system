# pyright: reportPrivateUsage=false
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from bi_system.dashboards.chart_contracts import ChartComponentConfig
from bi_system.dashboards.chart_query import (
    ChartFieldResource,
    ChartMetricResource,
    DashboardChartQueryError,
    _canonical_value,
    _chart_result,
    compile_dashboard_chart_query,
)
from bi_system.dashboards.filters import ResolvedScopedFilters
from bi_system.modeling.contracts import (
    AggregateFunction,
    MetricQuerySort,
    QuerySort,
    SortDirection,
    TimeGrain,
)
from bi_system.modeling.query_service import DatasetQueryResult


def _field(
    field_id: UUID,
    *,
    role: str,
    data_type: str,
    label: str,
) -> ChartFieldResource:
    return ChartFieldResource(
        field_id=field_id,
        label=label,
        role=role,
        data_type=data_type,
    )


def test_compile_metric_sort_and_time_grain_preserves_slot_mapping() -> None:
    dataset_id = uuid4()
    date_field_id = uuid4()
    metric_id = uuid4()
    config = ChartComponentConfig.model_validate(
        {
            "schema_version": 1,
            "title": "Monthly revenue",
            "description": None,
            "query": {
                "dataset_id": dataset_id,
                "dimensions": [
                    {
                        "field_id": date_field_id,
                        "slot_key": "month",
                        "time_grain": "month",
                    }
                ],
                "measures": [
                    {
                        "kind": "metric",
                        "metric_version_id": metric_id,
                        "slot_key": "revenue",
                    }
                ],
                "sort": [
                    {
                        "kind": "metric",
                        "metric_version_id": metric_id,
                        "direction": "desc",
                    }
                ],
            },
            "presentation": {},
        }
    )

    compiled = compile_dashboard_chart_query(
        component_id=uuid4(),
        component_type="line",
        config=config,
        fields={
            date_field_id: _field(
                date_field_id,
                role="dimension",
                data_type="date",
                label="Sold month",
            )
        },
        metrics={
            metric_id: ChartMetricResource(
                metric_version_id=metric_id,
                label="Revenue",
                data_type="decimal",
                unit="CNY",
            )
        },
        scoped_filters=ResolvedScopedFilters(filters=(), evidence=()),
    )

    assert compiled.request.dataset_id == dataset_id
    assert compiled.request.selections[0].output_name == "dimension"
    assert compiled.request.selections[0].time_grain is TimeGrain.MONTH
    assert compiled.request.metrics[0].output_name == "value_1"
    assert compiled.request.group_by == [date_field_id]
    assert compiled.request.order_by == [
        MetricQuerySort(metric_id=metric_id, direction=SortDirection.DESCENDING)
    ]
    assert [(column.slot_key, column.query_alias) for column in compiled.columns] == [
        ("month", "dimension"),
        ("revenue", "value_1"),
    ]
    assert compiled.columns[0].resource_id == date_field_id
    assert compiled.columns[1].resource_id == metric_id


def test_compile_top_n_adds_stable_dimension_tie_breaker() -> None:
    dataset_id = uuid4()
    dimension_id = uuid4()
    measure_id = uuid4()
    config = ChartComponentConfig.model_validate(
        {
            "schema_version": 1,
            "title": "Top regions",
            "description": None,
            "query": {
                "dataset_id": dataset_id,
                "dimensions": [{"field_id": dimension_id, "slot_key": "region"}],
                "measures": [
                    {
                        "kind": "field",
                        "field_id": measure_id,
                        "aggregate": "sum",
                        "slot_key": "revenue",
                    }
                ],
                "sort": [
                    {
                        "kind": "field",
                        "field_id": measure_id,
                        "aggregate": "sum",
                        "direction": "desc",
                    }
                ],
                "top_n": 10,
                "query_limit": 500,
            },
            "presentation": {},
        }
    )

    compiled = compile_dashboard_chart_query(
        component_id=uuid4(),
        component_type="ranking_table",
        config=config,
        fields={
            dimension_id: _field(
                dimension_id, role="dimension", data_type="string", label="Region"
            ),
            measure_id: _field(measure_id, role="measure", data_type="decimal", label="Revenue"),
        },
        metrics={},
        scoped_filters=ResolvedScopedFilters(filters=(), evidence=()),
    )

    assert compiled.request.limit == 10
    assert compiled.request.order_by == [
        QuerySort(
            field_id=measure_id,
            aggregate=AggregateFunction.SUM,
            direction=SortDirection.DESCENDING,
        ),
        QuerySort(field_id=dimension_id, direction=SortDirection.ASCENDING),
    ]


def test_compile_rejects_dimension_field_in_measure_slot() -> None:
    dimension_id = uuid4()
    measure_id = uuid4()
    config = ChartComponentConfig.model_validate(
        {
            "schema_version": 1,
            "title": "Invalid measure role",
            "query": {
                "dataset_id": uuid4(),
                "dimensions": [{"field_id": dimension_id, "slot_key": "category"}],
                "measures": [
                    {
                        "kind": "field",
                        "field_id": measure_id,
                        "aggregate": "sum",
                        "slot_key": "value",
                    }
                ],
            },
        }
    )

    with pytest.raises(DashboardChartQueryError) as captured:
        compile_dashboard_chart_query(
            component_id=uuid4(),
            component_type="bar",
            config=config,
            fields={
                dimension_id: _field(
                    dimension_id,
                    role="dimension",
                    data_type="string",
                    label="Category",
                ),
                measure_id: _field(
                    measure_id,
                    role="dimension",
                    data_type="decimal",
                    label="Misclassified value",
                ),
            },
            metrics={},
            scoped_filters=ResolvedScopedFilters(filters=(), evidence=()),
        )

    assert captured.value.code == "chart_slot_invalid"
    assert captured.value.config_path == "query.measures.0.field_id"


def test_top_n_rejects_dimension_sort_and_series_adds_stable_group_sorts() -> None:
    dimension_id = uuid4()
    series_id = uuid4()
    measure_id = uuid4()
    fields = {
        dimension_id: _field(dimension_id, role="dimension", data_type="string", label="Category"),
        series_id: _field(series_id, role="dimension", data_type="string", label="Series"),
        measure_id: _field(measure_id, role="measure", data_type="decimal", label="Value"),
    }
    base_query = {
        "dataset_id": uuid4(),
        "dimensions": [{"field_id": dimension_id, "slot_key": "category"}],
        "measures": [
            {
                "kind": "field",
                "field_id": measure_id,
                "aggregate": "sum",
                "slot_key": "value",
            }
        ],
    }
    top_n_config = ChartComponentConfig.model_validate(
        {
            "schema_version": 1,
            "title": "Invalid Top N",
            "query": {
                **base_query,
                "sort": [{"kind": "field", "field_id": dimension_id, "direction": "desc"}],
                "top_n": 5,
            },
        }
    )
    with pytest.raises(DashboardChartQueryError) as captured:
        compile_dashboard_chart_query(
            component_id=uuid4(),
            component_type="bar",
            config=top_n_config,
            fields=fields,
            metrics={},
            scoped_filters=ResolvedScopedFilters(filters=(), evidence=()),
        )
    assert captured.value.code == "top_n_requires_value_sort"

    series_config = ChartComponentConfig.model_validate(
        {
            "schema_version": 1,
            "title": "Series",
            "query": {
                **base_query,
                "series_dimension": {
                    "field_id": series_id,
                    "slot_key": "series",
                    "max_series": 5,
                },
                "sort": [
                    {
                        "kind": "field",
                        "field_id": measure_id,
                        "aggregate": "sum",
                        "direction": "desc",
                    }
                ],
            },
        }
    )
    compiled = compile_dashboard_chart_query(
        component_id=uuid4(),
        component_type="stacked_bar",
        config=series_config,
        fields=fields,
        metrics={},
        scoped_filters=ResolvedScopedFilters(filters=(), evidence=()),
    )
    assert compiled.request.order_by == [
        QuerySort(
            field_id=measure_id,
            aggregate=AggregateFunction.SUM,
            direction=SortDirection.DESCENDING,
        ),
        QuerySort(field_id=dimension_id, direction=SortDirection.ASCENDING),
        QuerySort(field_id=series_id, direction=SortDirection.ASCENDING),
    ]


def test_chart_result_canonicalizes_decimal_null_and_temporal_values() -> None:
    dimension_id = uuid4()
    measure_id = uuid4()
    config = ChartComponentConfig.model_validate(
        {
            "schema_version": 1,
            "title": "Detail",
            "description": None,
            "query": {
                "dataset_id": uuid4(),
                "dimensions": [{"field_id": dimension_id, "slot_key": "day"}],
                "measures": [
                    {
                        "kind": "field",
                        "field_id": measure_id,
                        "aggregate": "sum",
                        "slot_key": "amount",
                    }
                ],
            },
            "presentation": {},
        }
    )
    compiled = compile_dashboard_chart_query(
        component_id=uuid4(),
        component_type="bar",
        config=config,
        fields={
            dimension_id: _field(dimension_id, role="dimension", data_type="date", label="Day"),
            measure_id: _field(measure_id, role="measure", data_type="decimal", label="Amount"),
        },
        metrics={},
        scoped_filters=ResolvedScopedFilters(filters=(), evidence=()),
    )
    batch_id = uuid4()
    result = _chart_result(
        compiled,
        DatasetQueryResult(
            columns=("dimension", "value_1", "observed_at", "missing"),
            rows=(
                {
                    "dimension": date(2026, 7, 19),
                    "value_1": Decimal("12.3400"),
                    "observed_at": datetime(2026, 7, 19, 8, 30, tzinfo=UTC),
                    "missing": None,
                },
                {
                    "dimension": date(2026, 7, 20),
                    "value_1": None,
                    "observed_at": datetime(2026, 7, 20, 8, 30, tzinfo=UTC),
                    "missing": "hidden",
                },
            ),
            truncated=False,
            elapsed_ms=1.5,
            dataset_version=3,
            metric_version_ids=(),
            source_batch_ids=(batch_id,),
        ),
        warnings=(),
    )

    assert result.rows == (
        {
            "dimension": "2026-07-19",
            "value_1": "12.3400",
        },
        {"dimension": "2026-07-20", "value_1": None},
    )
    assert _canonical_value(datetime(2026, 7, 19, 8, 30, tzinfo=UTC)) == (
        "2026-07-19T08:30:00+00:00"
    )
    assert result.source_batch_ids == (batch_id,)
    assert all("sql" not in column.query_alias for column in result.columns)
