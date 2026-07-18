# pyright: reportAny=false, reportUnknownParameterType=false, reportMissingParameterType=false
# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false, reportPrivateUsage=false
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.dashboards import chart_query
from bi_system.dashboards.chart_contracts import (
    ChartComponentConfig,
    DashboardChartQueryRequest,
    PreviewChartComponent,
    RuntimeChartFilterScopes,
)
from bi_system.dashboards.chart_query import (
    ChartFieldResource,
    CompiledDashboardChartQuery,
    DashboardChartQueryError,
    execute_dashboard_chart_query,
    prepare_dashboard_chart_query,
)
from bi_system.dashboards.filters import ResolvedScopedFilters
from bi_system.dashboards.service import (
    DashboardCapability,
    DashboardComponentDetail,
    DashboardDetail,
    DashboardPageDetail,
)
from bi_system.identity import QueryPrincipal
from bi_system.modeling.expression import ComparisonPredicate
from bi_system.modeling.query_service import DatasetQueryResult, DatasetQueryTimeoutError
from sqlalchemy.orm import Session


def _principal() -> QueryPrincipal:
    return QueryPrincipal(
        user_id=uuid4(),
        workspace_id=uuid4(),
        permissions=frozenset({"dashboards:view", "datasets:query"}),
    )


def _chart_config(
    *,
    dataset_id: UUID,
    dimension_id: UUID,
    measure_id: UUID,
    component_filter: dict[str, object] | None = None,
    series_id: UUID | None = None,
    max_series: int = 5,
) -> ChartComponentConfig:
    query: dict[str, object] = {
        "dataset_id": dataset_id,
        "dimensions": [{"field_id": dimension_id, "slot_key": "category"}],
        "measures": [
            {
                "kind": "field",
                "field_id": measure_id,
                "aggregate": "sum",
                "slot_key": "value",
            }
        ],
        "query_limit": 100,
    }
    if series_id is not None:
        query["series_dimension"] = {
            "field_id": series_id,
            "slot_key": "series",
            "max_series": max_series,
        }
    return ChartComponentConfig.model_validate(
        {
            "schema_version": 1,
            "title": "Revenue",
            "description": None,
            "query": query,
            "component_filter": component_filter,
            "presentation": {},
        }
    )


def _dashboard(
    *,
    dashboard_id: UUID,
    page_id: UUID,
    component_id: UUID,
    config: ChartComponentConfig,
    capabilities: list[DashboardCapability],
    global_filter: dict[str, object] | None = None,
    page_filter: dict[str, object] | None = None,
) -> DashboardDetail:
    return DashboardDetail(
        id=dashboard_id,
        name="Dashboard",
        description=None,
        status="active",
        owner_name="Owner",
        updated_at=datetime(2026, 7, 19, tzinfo=UTC),
        current_version=1,
        page_count=1,
        capabilities=capabilities,
        revision=1,
        current_version_id=uuid4(),
        global_filter=global_filter,
        pages=[
            DashboardPageDetail(
                page_id=page_id,
                title="Overview",
                ordinal=0,
                page_filter=page_filter,
                components=[
                    DashboardComponentDetail(
                        component_id=component_id,
                        page_id=page_id,
                        component_type=(
                            "stacked_bar" if config.query.series_dimension is not None else "bar"
                        ),
                        config_version=1,
                        config=config.model_dump(mode="json"),
                        ordinal=0,
                    )
                ],
            )
        ],
        layouts=[],
        permissions=[],
    )


def _resources(
    dimension_id: UUID,
    measure_id: UUID,
    series_id: UUID | None = None,
) -> dict[UUID, ChartFieldResource]:
    resources = {
        dimension_id: ChartFieldResource(
            field_id=dimension_id,
            label="Category",
            role="dimension",
            data_type="string",
        ),
        measure_id: ChartFieldResource(
            field_id=measure_id,
            label="Revenue",
            role="measure",
            data_type="decimal",
        ),
    }
    if series_id is not None:
        resources[series_id] = ChartFieldResource(
            field_id=series_id,
            label="Series",
            role="dimension",
            data_type="string",
        )
    return resources


def test_saved_query_loads_persisted_config_and_preserves_filter_scope_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard_id = uuid4()
    page_id = uuid4()
    component_id = uuid4()
    dataset_id = uuid4()
    dimension_id = uuid4()
    measure_id = uuid4()
    filter_ids = (uuid4(), uuid4(), uuid4())

    def filter_value(field_id: UUID, value: str) -> dict[str, object]:
        return {
            "kind": "comparison",
            "field_id": field_id,
            "operator": "eq",
            "value": value,
        }

    config = _chart_config(
        dataset_id=dataset_id,
        dimension_id=dimension_id,
        measure_id=measure_id,
        component_filter=filter_value(filter_ids[2], "component"),
    )
    dashboard = _dashboard(
        dashboard_id=dashboard_id,
        page_id=page_id,
        component_id=component_id,
        config=config,
        capabilities=["view"],
        global_filter=filter_value(filter_ids[0], "global"),
        page_filter=filter_value(filter_ids[1], "page"),
    )
    monkeypatch.setattr(chart_query, "get_dashboard", lambda *_args, **_kwargs: dashboard)
    monkeypatch.setattr(
        chart_query,
        "_resolve_resources",
        lambda *_args, **_kwargs: (_resources(dimension_id, measure_id), {}),
    )

    compiled = prepare_dashboard_chart_query(
        cast(Session, object()),
        principal=_principal(),
        request=DashboardChartQueryRequest(
            dashboard_id=dashboard_id,
            dashboard_version_id=dashboard.current_version_id,
            page_id=page_id,
            component_id=component_id,
        ),
        workspace_timezone="UTC",
    )

    assert compiled.component_id == component_id
    assert len(compiled.scoped_filters.filters) == 3
    assert [
        predicate.field_id
        for predicate in compiled.scoped_filters.filters
        if isinstance(predicate, ComparisonPredicate)
    ] == list(filter_ids)


def test_version_conflict_and_runtime_filters_override_persisted_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard_id = uuid4()
    page_id = uuid4()
    component_id = uuid4()
    dimension_id = uuid4()
    measure_id = uuid4()
    persisted_field_id = uuid4()
    runtime_field_id = uuid4()
    persisted_filter: dict[str, object] = {
        "kind": "comparison",
        "field_id": persisted_field_id,
        "operator": "eq",
        "value": "persisted",
    }
    runtime_filter: dict[str, object] = {
        "kind": "comparison",
        "field_id": runtime_field_id,
        "operator": "eq",
        "value": "runtime",
    }
    config = _chart_config(
        dataset_id=uuid4(),
        dimension_id=dimension_id,
        measure_id=measure_id,
        component_filter=persisted_filter,
    )
    dashboard = _dashboard(
        dashboard_id=dashboard_id,
        page_id=page_id,
        component_id=component_id,
        config=config,
        capabilities=["view"],
        global_filter=persisted_filter,
        page_filter=persisted_filter,
    )
    monkeypatch.setattr(chart_query, "get_dashboard", lambda *_args, **_kwargs: dashboard)
    monkeypatch.setattr(
        chart_query,
        "_resolve_resources",
        lambda *_args, **_kwargs: (_resources(dimension_id, measure_id), {}),
    )
    with pytest.raises(DashboardChartQueryError) as conflict:
        prepare_dashboard_chart_query(
            cast(Session, object()),
            principal=_principal(),
            request=DashboardChartQueryRequest(
                dashboard_id=dashboard_id,
                dashboard_version_id=uuid4(),
                page_id=page_id,
                component_id=component_id,
            ),
            workspace_timezone="UTC",
        )
    assert conflict.value.code == "dashboard_version_conflict"

    compiled = prepare_dashboard_chart_query(
        cast(Session, object()),
        principal=_principal(),
        request=DashboardChartQueryRequest(
            dashboard_id=dashboard_id,
            dashboard_version_id=dashboard.current_version_id,
            page_id=page_id,
            component_id=component_id,
            runtime_filters=RuntimeChartFilterScopes(global_filter=runtime_filter),
        ),
        workspace_timezone="UTC",
    )
    assert len(compiled.scoped_filters.filters) == 1
    resolved = compiled.scoped_filters.filters[0]
    assert isinstance(resolved, ComparisonPredicate)
    assert resolved.field_id == runtime_field_id


def test_dataset_permission_is_checked_before_field_and_metric_resolution() -> None:
    principal = QueryPrincipal(
        user_id=uuid4(),
        workspace_id=uuid4(),
        permissions=frozenset({"dashboards:view"}),
    )

    class DatasetOnlySession:
        def get(self, _model: object, _identifier: object) -> object:
            return type(
                "VisibleDataset",
                (),
                {
                    "workspace_id": principal.workspace_id,
                    "status": "active",
                    "deleted_at": None,
                },
            )()

        def scalars(self, _statement: object) -> object:
            raise AssertionError("field resolution must not run before permission denial")

    with pytest.raises(DashboardChartQueryError) as captured:
        chart_query._resolve_resources(
            cast(Session, DatasetOnlySession()),
            principal=principal,
            query=_chart_config(
                dataset_id=uuid4(),
                dimension_id=uuid4(),
                measure_id=uuid4(),
            ).query,
        )
    assert captured.value.code == "dataset_query_forbidden"


def test_preview_requires_edit_capability_and_uses_unsaved_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard_id = uuid4()
    page_id = uuid4()
    component_id = uuid4()
    dataset_id = uuid4()
    dimension_id = uuid4()
    measure_id = uuid4()
    saved_config = _chart_config(
        dataset_id=dataset_id,
        dimension_id=dimension_id,
        measure_id=measure_id,
    )
    preview_config = saved_config.model_copy(update={"title": "Unsaved title"})
    dashboard = _dashboard(
        dashboard_id=dashboard_id,
        page_id=page_id,
        component_id=component_id,
        config=saved_config,
        capabilities=["view"],
    )
    monkeypatch.setattr(chart_query, "get_dashboard", lambda *_args, **_kwargs: dashboard)
    monkeypatch.setattr(
        chart_query,
        "_resolve_resources",
        lambda *_args, **_kwargs: (_resources(dimension_id, measure_id), {}),
    )
    request = DashboardChartQueryRequest(
        dashboard_id=dashboard_id,
        dashboard_version_id=dashboard.current_version_id,
        page_id=page_id,
        component_id=component_id,
        preview_component=PreviewChartComponent(
            component_id=component_id,
            page_id=page_id,
            component_type="bar",
            config_version=1,
            config=preview_config,
        ),
    )

    with pytest.raises(DashboardChartQueryError) as forbidden:
        prepare_dashboard_chart_query(
            cast(Session, object()),
            principal=_principal(),
            request=request,
            workspace_timezone="UTC",
        )
    assert forbidden.value.code == "dashboard_forbidden"

    editable = _dashboard(
        dashboard_id=dashboard_id,
        page_id=page_id,
        component_id=component_id,
        config=saved_config,
        capabilities=["view", "edit"],
    )
    monkeypatch.setattr(chart_query, "get_dashboard", lambda *_args, **_kwargs: editable)
    request = request.model_copy(update={"dashboard_version_id": editable.current_version_id})
    compiled = prepare_dashboard_chart_query(
        cast(Session, object()),
        principal=_principal(),
        request=request,
        workspace_timezone="UTC",
    )
    assert compiled.component_id == component_id


def _series_compiled(*, max_series: int = 2) -> CompiledDashboardChartQuery:
    dimension_id = uuid4()
    measure_id = uuid4()
    series_id = uuid4()
    config = _chart_config(
        dataset_id=uuid4(),
        dimension_id=dimension_id,
        measure_id=measure_id,
        series_id=series_id,
        max_series=max_series,
    )
    return chart_query.compile_dashboard_chart_query(
        component_id=uuid4(),
        component_type="stacked_bar",
        config=config,
        fields=_resources(dimension_id, measure_id, series_id),
        metrics={},
        scoped_filters=ResolvedScopedFilters(filters=(), evidence=()),
    )


def _result(
    row_count: int,
    *,
    truncated: bool = False,
) -> DatasetQueryResult:
    return DatasetQueryResult(
        columns=("dimension", "series", "value_1"),
        rows=tuple(
            {"dimension": f"d{index}", "series": "s", "value_1": index}
            for index in range(row_count)
        ),
        truncated=truncated,
        elapsed_ms=1.0,
        dataset_version=1,
        metric_version_ids=(),
        source_batch_ids=(uuid4(),),
    )


def _request(component_id: UUID) -> DashboardChartQueryRequest:
    return DashboardChartQueryRequest(
        dashboard_id=uuid4(),
        dashboard_version_id=uuid4(),
        page_id=uuid4(),
        component_id=component_id,
    )


def test_series_preflight_uses_governed_queries_before_main_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = _series_compiled()
    monkeypatch.setattr(chart_query, "prepare_dashboard_chart_query", lambda *_a, **_k: compiled)
    results = iter((_result(2), _result(2), _result(4)))
    calls: list[dict[str, object]] = []

    def fake_execute(*_args, **kwargs):
        calls.append(kwargs)
        return next(results)

    monkeypatch.setattr(chart_query, "execute_dataset_query", fake_execute)

    result = execute_dashboard_chart_query(
        cast(Session, object()),
        principal=_principal(),
        request=_request(compiled.component_id),
        workspace_timezone="UTC",
        timeout_seconds=3.0,
    )

    assert len(calls) == 3
    assert all(call["scoped_filters"] == compiled.scoped_filters.filters for call in calls)
    assert len(result.rows) == 4
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("results", "expected_code"),
    [
        ((_result(2), _result(2, truncated=True)), "series_cardinality_exceeded"),
        ((_result(2), _result(2), _result(4, truncated=True)), "series_result_truncated"),
        ((_result(2), _result(2), _result(5)), "series_cardinality_evidence_stale"),
    ],
)
def test_series_queries_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    results: tuple[DatasetQueryResult, ...],
    expected_code: str,
) -> None:
    compiled = _series_compiled()
    monkeypatch.setattr(chart_query, "prepare_dashboard_chart_query", lambda *_a, **_k: compiled)
    result_iterator = iter(results)
    monkeypatch.setattr(
        chart_query,
        "execute_dataset_query",
        lambda *_args, **_kwargs: next(result_iterator),
    )

    with pytest.raises(DashboardChartQueryError) as captured:
        execute_dashboard_chart_query(
            cast(Session, object()),
            principal=_principal(),
            request=_request(compiled.component_id),
            workspace_timezone="UTC",
            timeout_seconds=3.0,
        )
    assert captured.value.code == expected_code


def test_m2_query_errors_keep_stable_code_action_and_no_shortcut_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = _series_compiled()
    compiled = CompiledDashboardChartQuery(
        component_id=compiled.component_id,
        component_type=compiled.component_type,
        request=compiled.request,
        columns=compiled.columns,
        scoped_filters=compiled.scoped_filters,
        primary_dimension=compiled.primary_dimension,
        series_field_id=None,
        series_maximum=None,
    )
    monkeypatch.setattr(chart_query, "prepare_dashboard_chart_query", lambda *_a, **_k: compiled)
    upstream = DatasetQueryTimeoutError(
        "dataset_query_timeout",
        "Dataset query exceeded its execution deadline",
        "Reduce the query scope",
    )

    def fail(*_args, **_kwargs):
        raise upstream

    monkeypatch.setattr(chart_query, "execute_dataset_query", fail)
    with pytest.raises(DashboardChartQueryError) as captured:
        execute_dashboard_chart_query(
            cast(Session, object()),
            principal=_principal(),
            request=_request(compiled.component_id),
            workspace_timezone="UTC",
            timeout_seconds=3.0,
        )
    assert captured.value.code == upstream.code
    assert captured.value.action == upstream.action
