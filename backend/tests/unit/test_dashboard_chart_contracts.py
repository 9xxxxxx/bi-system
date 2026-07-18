# pyright: reportUnknownVariableType=false
from uuid import UUID, uuid4

import pytest
from bi_system.dashboards.chart_contracts import (
    ChartComponentConfig,
    DashboardChartQueryRequest,
    PreviewChartComponent,
    RuntimeChartFilterScopes,
)
from pydantic import ValidationError


def _bar_config(
    *,
    dataset_id: UUID | None = None,
    dimension_id: UUID | None = None,
    measure_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "title": "Revenue by region",
        "description": None,
        "query": {
            "dataset_id": dataset_id or uuid4(),
            "dimensions": [
                {
                    "field_id": dimension_id or uuid4(),
                    "slot_key": "category",
                }
            ],
            "measures": [
                {
                    "kind": "field",
                    "field_id": measure_id or uuid4(),
                    "aggregate": "sum",
                    "slot_key": "value",
                }
            ],
        },
        "presentation": {},
    }


def test_chart_component_config_accepts_r1_persisted_title_and_description() -> None:
    config = ChartComponentConfig.model_validate(
        {
            **_bar_config(),
            "description": "Gross revenue",
        }
    )

    assert config.title == "Revenue by region"
    assert config.description == "Gross revenue"


@pytest.mark.parametrize(
    "mutation",
    [
        {"title": None},
        {"schema_version": 2},
        {"sql": "select * from revenue"},
    ],
)
def test_chart_component_config_rejects_missing_version_or_unsafe_extra_fields(
    mutation: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ChartComponentConfig.model_validate({**_bar_config(), **mutation})


def test_chart_presentation_rejects_recursive_physical_identifiers() -> None:
    payload = _bar_config()
    payload["presentation"] = {"tooltip": {"physical_column_name": "secret"}}
    with pytest.raises(ValidationError, match="forbidden key"):
        ChartComponentConfig.model_validate(payload)


def test_chart_query_rejects_duplicate_slots_and_unselected_sort_targets() -> None:
    duplicate = _bar_config()
    duplicate_query = duplicate["query"]
    assert isinstance(duplicate_query, dict)
    measures = duplicate_query["measures"]
    assert isinstance(measures, list)
    measure = measures[0]
    assert isinstance(measure, dict)
    measure["slot_key"] = "category"
    with pytest.raises(ValidationError, match="slot_key values must be unique"):
        ChartComponentConfig.model_validate(duplicate)

    unknown_sort = _bar_config()
    unknown_query = unknown_sort["query"]
    assert isinstance(unknown_query, dict)
    unknown_query["sort"] = [
        {
            "kind": "metric",
            "metric_version_id": uuid4(),
            "direction": "desc",
        }
    ]
    with pytest.raises(ValidationError, match="selected metric"):
        ChartComponentConfig.model_validate(unknown_sort)


def test_series_dimension_rejects_top_n_and_invalid_chart_slot_combinations() -> None:
    series_top_n = _bar_config()
    query = series_top_n["query"]
    assert isinstance(query, dict)
    query["series_dimension"] = {
        "field_id": uuid4(),
        "slot_key": "series",
        "max_series": 5,
    }
    query["top_n"] = 10
    with pytest.raises(ValidationError, match="cannot be combined with Top N"):
        ChartComponentConfig.model_validate(series_top_n)

    config = ChartComponentConfig.model_validate(_bar_config())
    with pytest.raises(ValidationError, match="requires 0 dimensions"):
        PreviewChartComponent(
            component_id=uuid4(),
            page_id=uuid4(),
            component_type="kpi",
            config_version=1,
            config=config,
        )

    series_only = _bar_config()
    series_query = series_only["query"]
    assert isinstance(series_query, dict)
    series_query["series_dimension"] = {
        "field_id": uuid4(),
        "slot_key": "series",
        "max_series": 5,
    }
    with pytest.raises(ValidationError, match="does not support a series dimension"):
        PreviewChartComponent(
            component_id=uuid4(),
            page_id=uuid4(),
            component_type="ranking_table",
            config_version=1,
            config=ChartComponentConfig.model_validate(series_only),
        )


def test_preview_identifiers_must_match_request_context() -> None:
    page_id = uuid4()
    component_id = uuid4()
    preview = PreviewChartComponent(
        component_id=uuid4(),
        page_id=page_id,
        component_type="bar",
        config_version=1,
        config=ChartComponentConfig.model_validate(_bar_config()),
    )

    with pytest.raises(ValidationError, match="identifiers must match"):
        DashboardChartQueryRequest(
            dashboard_id=uuid4(),
            dashboard_version_id=uuid4(),
            page_id=page_id,
            component_id=component_id,
            preview_component=preview,
        )


def test_request_requires_version_and_runtime_filter_scopes_are_strict() -> None:
    with pytest.raises(ValidationError, match="dashboard_version_id"):
        DashboardChartQueryRequest.model_validate(
            {
                "dashboard_id": uuid4(),
                "page_id": uuid4(),
                "component_id": uuid4(),
            }
        )
    scopes = RuntimeChartFilterScopes.model_validate(
        {
            "global_filter": {
                "kind": "relative_date",
                "field_id": uuid4(),
                "field_type": "date",
                "period": "today",
            }
        }
    )
    assert scopes.global_filter is not None
    with pytest.raises(ValidationError):
        RuntimeChartFilterScopes.model_validate({"unknown_scope": None})
