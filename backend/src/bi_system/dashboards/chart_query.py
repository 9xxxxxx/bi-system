from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from bi_system.dashboards.chart_contracts import (
    ChartComponentConfig,
    ChartComponentType,
    ChartDimension,
    ChartFieldMeasure,
    ChartMetricMeasure,
    ChartMetricSort,
    ChartQuerySpec,
    DashboardChartQueryRequest,
    PreviewChartComponent,
)
from bi_system.dashboards.errors import DashboardForbiddenError, DashboardServiceError
from bi_system.dashboards.filters import (
    DashboardFilterError,
    ResolvedFilterEvidence,
    ResolvedScopedFilters,
    resolve_scoped_filters,
)
from bi_system.dashboards.service import DashboardDetail, get_dashboard
from bi_system.db.models.modeling import Dataset, DatasetField, Metric
from bi_system.identity import QueryPrincipal
from bi_system.modeling.contracts import (
    AggregateFunction,
    DatasetMetricSelection,
    DatasetQueryRequest,
    MetricQuerySort,
    QuerySelection,
    QuerySort,
    SortDirection,
    TimeGrain,
)
from bi_system.modeling.query_service import (
    DatasetQueryError,
    DatasetQueryResult,
    execute_dataset_query,
    validate_dataset_query,
)


@dataclass(frozen=True, slots=True)
class ChartFieldResource:
    field_id: UUID
    label: str
    role: str
    data_type: str


@dataclass(frozen=True, slots=True)
class ChartMetricResource:
    metric_version_id: UUID
    label: str
    data_type: str
    unit: str | None


@dataclass(frozen=True, slots=True)
class ChartColumn:
    slot_key: str
    query_alias: str
    resource_kind: Literal["field", "metric"]
    resource_id: UUID
    aggregate: str | None
    label: str
    data_type: str
    unit: str | None


@dataclass(frozen=True, slots=True)
class CompiledDashboardChartQuery:
    component_id: UUID
    component_type: ChartComponentType
    request: DatasetQueryRequest
    columns: tuple[ChartColumn, ...]
    scoped_filters: ResolvedScopedFilters
    primary_dimension: ChartDimension | None
    series_field_id: UUID | None
    series_maximum: int | None


@dataclass(frozen=True, slots=True)
class DashboardChartValidation:
    valid: bool
    component_id: UUID
    columns: tuple[ChartColumn, ...]
    dataset_version: int
    metric_version_ids: tuple[UUID, ...]
    resolved_filters: tuple[ResolvedFilterEvidence, ...]


@dataclass(frozen=True, slots=True)
class ChartQueryWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class DashboardChartResult:
    request_id: UUID
    component_id: UUID
    columns: tuple[ChartColumn, ...]
    rows: tuple[dict[str, object], ...]
    truncated: bool
    elapsed_ms: float
    dataset_version: int
    metric_version_ids: tuple[UUID, ...]
    source_batch_ids: tuple[UUID, ...]
    resolved_filters: tuple[ResolvedFilterEvidence, ...]
    warnings: tuple[ChartQueryWarning, ...]


class DashboardChartQueryError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        action: str,
        *,
        config_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.action = action
        self.config_path = config_path


_CHART_ACTION = "Correct the chart configuration and try again"
_CHART_TYPES: frozenset[str] = frozenset(
    {
        "kpi",
        "trend_indicator",
        "target_progress",
        "detail_table",
        "ranking_table",
        "bar",
        "horizontal_bar",
        "stacked_bar",
        "line",
        "area",
        "pie",
        "donut",
    }
)


def validate_dashboard_chart_query(
    session: Session,
    *,
    principal: QueryPrincipal,
    request: DashboardChartQueryRequest,
    workspace_timezone: str,
    timeout_seconds: float,
) -> DashboardChartValidation:
    compiled = prepare_dashboard_chart_query(
        session,
        principal=principal,
        request=request,
        workspace_timezone=workspace_timezone,
    )
    if compiled.series_field_id is not None:
        _validate_series_cardinality(
            session,
            principal=principal,
            compiled=compiled,
            timeout_seconds=timeout_seconds,
        )
    try:
        prepared = validate_dataset_query(
            session,
            principal=principal,
            request=compiled.request,
            scoped_filters=compiled.scoped_filters.filters,
        )
    except DatasetQueryError as exc:
        raise _chart_error_from_dataset(exc) from exc
    return DashboardChartValidation(
        valid=True,
        component_id=compiled.component_id,
        columns=compiled.columns,
        dataset_version=prepared.dataset.version,
        metric_version_ids=prepared.metric_version_ids,
        resolved_filters=compiled.scoped_filters.evidence,
    )


def execute_dashboard_chart_query(
    session: Session,
    *,
    principal: QueryPrincipal,
    request: DashboardChartQueryRequest,
    workspace_timezone: str,
    timeout_seconds: float,
) -> DashboardChartResult:
    compiled = prepare_dashboard_chart_query(
        session,
        principal=principal,
        request=request,
        workspace_timezone=workspace_timezone,
    )
    series_row_upper_bound: int | None = None
    if compiled.series_field_id is not None:
        series_row_upper_bound = _validate_series_cardinality(
            session,
            principal=principal,
            compiled=compiled,
            timeout_seconds=timeout_seconds,
        )
    try:
        result = execute_dataset_query(
            session,
            principal=principal,
            request=compiled.request,
            timeout_seconds=timeout_seconds,
            scoped_filters=compiled.scoped_filters.filters,
        )
    except DatasetQueryError as exc:
        raise _chart_error_from_dataset(exc) from exc
    if series_row_upper_bound is not None:
        if result.truncated:
            raise DashboardChartQueryError(
                "series_result_truncated",
                "Truncated series results cannot preserve complete primary groups",
                "Reduce the dimension cardinality or increase the governed query limit",
            )
        if len(result.rows) > series_row_upper_bound:
            raise DashboardChartQueryError(
                "series_cardinality_evidence_stale",
                "Series result exceeds the governed cardinality preflight",
                "Refresh the dataset and retry the chart query",
            )
    warnings = (
        (
            ChartQueryWarning(
                code="query_result_truncated",
                message="The chart result reached its configured row limit",
            ),
        )
        if result.truncated
        else ()
    )
    return _chart_result(compiled, result, warnings=warnings)


def prepare_dashboard_chart_query(
    session: Session,
    *,
    principal: QueryPrincipal,
    request: DashboardChartQueryRequest,
    workspace_timezone: str,
) -> CompiledDashboardChartQuery:
    try:
        dashboard = get_dashboard(
            session,
            principal=principal,
            dashboard_id=request.dashboard_id,
        )
    except DashboardForbiddenError as exc:
        raise DashboardChartQueryError(
            exc.code,
            str(exc),
            "Ask the dashboard owner for view access",
        ) from exc
    except DashboardServiceError as exc:
        raise DashboardChartQueryError(exc.code, str(exc), "Refresh the dashboard") from exc
    if dashboard.current_version_id != request.dashboard_version_id:
        raise DashboardChartQueryError(
            "dashboard_version_conflict",
            "Dashboard version does not match the current version",
            "Refresh the dashboard and retry against its current version",
        )
    component_type, config, page_filter = _resolve_component(dashboard, request)
    if request.preview_component is not None and "edit" not in dashboard.capabilities:
        raise DashboardChartQueryError(
            "dashboard_forbidden",
            "Dashboard edit capability is required for preview queries",
            "Ask the dashboard owner for edit access",
        )
    try:
        runtime_filters = request.runtime_filters
        scoped_filters = resolve_scoped_filters(
            (dashboard.global_filter if runtime_filters is None else runtime_filters.global_filter),
            page_filter if runtime_filters is None else runtime_filters.page_filter,
            (
                config.component_filter
                if runtime_filters is None
                else runtime_filters.component_filter
            ),
            workspace_timezone,
        )
    except DashboardFilterError as exc:
        raise DashboardChartQueryError(exc.code, str(exc), exc.action) from exc
    fields, metrics = _resolve_resources(
        session,
        principal=principal,
        query=config.query,
    )
    return compile_dashboard_chart_query(
        component_id=request.component_id,
        component_type=component_type,
        config=config,
        fields=fields,
        metrics=metrics,
        scoped_filters=scoped_filters,
    )


def compile_dashboard_chart_query(
    *,
    component_id: UUID,
    component_type: ChartComponentType,
    config: ChartComponentConfig,
    fields: dict[UUID, ChartFieldResource],
    metrics: dict[UUID, ChartMetricResource],
    scoped_filters: ResolvedScopedFilters,
) -> CompiledDashboardChartQuery:
    query = config.query
    selections: list[QuerySelection] = []
    metric_selections: list[DatasetMetricSelection] = []
    columns: list[ChartColumn] = []
    dimension_aliases: dict[UUID, tuple[str, TimeGrain | None]] = {}
    for index, dimension in enumerate(query.dimensions, start=1):
        resource = _required_field(fields, dimension.field_id, path=f"query.dimensions.{index - 1}")
        if resource.role != "dimension":
            raise _chart_configuration_error(
                "chart_slot_invalid", "Dimension slots require dimension fields", "query.dimensions"
            )
        grain = TimeGrain(dimension.time_grain) if dimension.time_grain is not None else None
        if grain is not None and resource.data_type not in {"date", "datetime"}:
            raise _chart_configuration_error(
                "invalid_time_grain_type",
                "Time grains require a date or datetime field",
                f"query.dimensions.{index - 1}.time_grain",
            )
        alias = "dimension" if len(query.dimensions) == 1 else f"dimension_{index}"
        selections.append(
            QuerySelection(
                field_id=dimension.field_id,
                output_name=alias,
                time_grain=grain,
            )
        )
        dimension_aliases[dimension.field_id] = (alias, grain)
        columns.append(
            ChartColumn(
                slot_key=dimension.slot_key,
                query_alias=alias,
                resource_kind="field",
                resource_id=dimension.field_id,
                aggregate=None,
                label=resource.label,
                data_type="string" if grain is not None else resource.data_type,
                unit=None,
            )
        )
    series_field_id: UUID | None = None
    if query.series_dimension is not None:
        series = query.series_dimension
        resource = _required_field(fields, series.field_id, path="query.series_dimension.field_id")
        if resource.role != "dimension":
            raise _chart_configuration_error(
                "chart_slot_invalid",
                "Series slots require dimension fields",
                "query.series_dimension",
            )
        series_field_id = series.field_id
        selections.append(QuerySelection(field_id=series.field_id, output_name="series"))
        dimension_aliases[series.field_id] = ("series", None)
        columns.append(
            ChartColumn(
                slot_key=series.slot_key,
                query_alias="series",
                resource_kind="field",
                resource_id=series.field_id,
                aggregate=None,
                label=resource.label,
                data_type=resource.data_type,
                unit=None,
            )
        )
    for index, measure in enumerate(query.measures, start=1):
        alias = f"value_{index}"
        if isinstance(measure, ChartFieldMeasure):
            resource = _required_field(
                fields, measure.field_id, path=f"query.measures.{index - 1}.field_id"
            )
            if resource.role != "measure":
                raise _chart_configuration_error(
                    "chart_slot_invalid",
                    "Field measure slots require measure fields",
                    f"query.measures.{index - 1}.field_id",
                )
            selections.append(
                QuerySelection(
                    field_id=measure.field_id,
                    output_name=alias,
                    aggregate=measure.aggregate,
                )
            )
            data_type = (
                "integer"
                if measure.aggregate in {AggregateFunction.COUNT, AggregateFunction.COUNT_DISTINCT}
                else resource.data_type
            )
            columns.append(
                ChartColumn(
                    slot_key=measure.slot_key,
                    query_alias=alias,
                    resource_kind="field",
                    resource_id=measure.field_id,
                    aggregate=measure.aggregate.value,
                    label=resource.label,
                    data_type=data_type,
                    unit=None,
                )
            )
        else:
            resource = _required_metric(
                metrics,
                measure.metric_version_id,
                path=f"query.measures.{index - 1}.metric_version_id",
            )
            metric_selections.append(
                DatasetMetricSelection(
                    metric_id=measure.metric_version_id,
                    output_name=alias,
                )
            )
            columns.append(
                ChartColumn(
                    slot_key=measure.slot_key,
                    query_alias=alias,
                    resource_kind="metric",
                    resource_id=measure.metric_version_id,
                    aggregate=None,
                    label=resource.label,
                    data_type=resource.data_type,
                    unit=resource.unit,
                )
            )
    order_by = _compile_sorts(query, dimension_aliases)
    if not order_by:
        order_by = _default_sorts(component_type, query)
    if query.top_n is not None:
        order_by = _top_n_sorts(query, order_by)
    order_by = _stable_sorts(component_type, query, order_by)
    group_by = (
        [dimension.field_id for dimension in query.dimensions]
        + ([series_field_id] if series_field_id is not None else [])
        if query.measures
        else []
    )
    limit = (
        1
        if component_type in {"kpi", "target_progress"}
        else (query.top_n if query.top_n is not None else query.query_limit)
    )
    try:
        dataset_request = DatasetQueryRequest(
            dataset_id=query.dataset_id,
            selections=selections,
            metrics=metric_selections,
            group_by=group_by,
            order_by=order_by,
            limit=limit,
        )
    except ValidationError as exc:
        raise _chart_configuration_error(
            "chart_config_invalid",
            "Chart query cannot compile to the governed M2 contract",
            "query",
        ) from exc
    return CompiledDashboardChartQuery(
        component_id=component_id,
        component_type=component_type,
        request=dataset_request,
        columns=tuple(columns),
        scoped_filters=scoped_filters,
        primary_dimension=query.dimensions[0] if query.dimensions else None,
        series_field_id=series_field_id,
        series_maximum=(
            query.series_dimension.max_series if query.series_dimension is not None else None
        ),
    )


def _resolve_component(
    dashboard: DashboardDetail,
    request: DashboardChartQueryRequest,
) -> tuple[ChartComponentType, ChartComponentConfig, dict[str, object] | None]:
    page = next((item for item in dashboard.pages if item.page_id == request.page_id), None)
    if page is None:
        raise DashboardChartQueryError(
            "dashboard_page_not_found", "Dashboard page was not found", "Refresh the dashboard"
        )
    preview = request.preview_component
    if preview is not None:
        return preview.component_type, preview.config, page.page_filter
    component = next(
        (item for item in page.components if item.component_id == request.component_id), None
    )
    if component is None:
        raise DashboardChartQueryError(
            "dashboard_component_not_found",
            "Dashboard component was not found",
            "Refresh the dashboard",
        )
    if component.component_type not in _CHART_TYPES:
        raise DashboardChartQueryError(
            "chart_component_not_queryable",
            "Dashboard component does not contain a chart query",
            "Choose a queryable chart component",
        )
    try:
        preview_component = PreviewChartComponent.model_validate(
            {
                "component_id": component.component_id,
                "page_id": component.page_id,
                "component_type": component.component_type,
                "config_version": component.config_version,
                "config": component.config,
            }
        )
    except ValidationError as exc:
        raise _chart_configuration_error(
            "chart_config_invalid", "Stored chart component configuration is invalid", "config"
        ) from exc
    return preview_component.component_type, preview_component.config, page.page_filter


def _resolve_resources(
    session: Session,
    *,
    principal: QueryPrincipal,
    query: ChartQuerySpec,
) -> tuple[dict[UUID, ChartFieldResource], dict[UUID, ChartMetricResource]]:
    dataset = session.get(Dataset, query.dataset_id)
    if (
        dataset is None
        or dataset.workspace_id != principal.workspace_id
        or dataset.status == "deleted"
        or dataset.deleted_at is not None
    ):
        raise DashboardChartQueryError(
            "dataset_not_found", "Dataset was not found", "Choose an available dataset"
        )
    if not principal.has_permission("datasets:query"):
        raise DashboardChartQueryError(
            "dataset_query_forbidden",
            "Dataset query permission is required",
            "Ask a workspace administrator for query permission",
        )
    field_ids = {dimension.field_id for dimension in query.dimensions}
    if query.series_dimension is not None:
        field_ids.add(query.series_dimension.field_id)
    field_ids.update(
        measure.field_id for measure in query.measures if isinstance(measure, ChartFieldMeasure)
    )
    fields = list(
        session.scalars(
            select(DatasetField).where(
                DatasetField.dataset_id == dataset.id,
                DatasetField.id.in_(field_ids),
                DatasetField.hidden.is_(False),
            )
        ).all()
    )
    fields_by_id = {
        field.id: ChartFieldResource(
            field_id=field.id,
            label=field.label,
            role=field.field_role,
            data_type=field.data_type,
        )
        for field in fields
    }
    if set(fields_by_id) != field_ids:
        raise DashboardChartQueryError(
            "dataset_field_not_found",
            "One or more chart fields were not found",
            "Choose visible fields from the selected dataset",
        )
    metric_ids = {
        measure.metric_version_id
        for measure in query.measures
        if isinstance(measure, ChartMetricMeasure)
    }
    metrics = list(
        session.scalars(
            select(Metric).where(
                Metric.id.in_(metric_ids),
                Metric.workspace_id == principal.workspace_id,
                Metric.dataset_id == dataset.id,
                Metric.status == "active",
                Metric.deleted_at.is_(None),
            )
        ).all()
    )
    metrics_by_id = {
        metric.id: ChartMetricResource(
            metric_version_id=metric.id,
            label=metric.name,
            data_type=metric.result_type,
            unit=metric.unit,
        )
        for metric in metrics
    }
    if set(metrics_by_id) != metric_ids:
        raise DashboardChartQueryError(
            "metric_not_found",
            "One or more active metric versions were not found",
            "Choose active metrics from the selected dataset",
        )
    return fields_by_id, metrics_by_id


def _compile_sorts(
    query: ChartQuerySpec,
    dimension_aliases: dict[UUID, tuple[str, TimeGrain | None]],
) -> list[QuerySort | MetricQuerySort]:
    sorts: list[QuerySort | MetricQuerySort] = []
    for sort in query.sort:
        if isinstance(sort, ChartMetricSort):
            sorts.append(
                MetricQuerySort(metric_id=sort.metric_version_id, direction=sort.direction)
            )
            continue
        grain = dimension_aliases.get(sort.field_id, ("", None))[1]
        sorts.append(
            QuerySort(
                field_id=sort.field_id,
                aggregate=sort.aggregate,
                time_grain=grain if sort.aggregate is None else None,
                direction=sort.direction,
            )
        )
    return sorts


def _default_sorts(
    component_type: ChartComponentType,
    query: ChartQuerySpec,
) -> list[QuerySort | MetricQuerySort]:
    if component_type == "ranking_table" or query.top_n is not None:
        return [_measure_sort(query, 0, SortDirection.DESCENDING)]
    if query.dimensions:
        dimension = query.dimensions[0]
        return [
            QuerySort(
                field_id=dimension.field_id,
                time_grain=(
                    TimeGrain(dimension.time_grain) if dimension.time_grain is not None else None
                ),
                direction=SortDirection.ASCENDING,
            )
        ]
    return []


def _top_n_sorts(
    query: ChartQuerySpec,
    sorts: list[QuerySort | MetricQuerySort],
) -> list[QuerySort | MetricQuerySort]:
    if not query.dimensions:
        raise _chart_configuration_error(
            "chart_slot_invalid", "Top N requires a primary dimension", "query.top_n"
        )
    first = sorts[0] if sorts else _measure_sort(query, 0, SortDirection.DESCENDING)
    selected_field_measures = {
        (measure.field_id, measure.aggregate)
        for measure in query.measures
        if isinstance(measure, ChartFieldMeasure)
    }
    selected_metric_measures = {
        measure.metric_version_id
        for measure in query.measures
        if isinstance(measure, ChartMetricMeasure)
    }
    is_value_sort = (
        isinstance(first, QuerySort)
        and (first.field_id, first.aggregate) in selected_field_measures
    ) or (isinstance(first, MetricQuerySort) and first.metric_id in selected_metric_measures)
    if not is_value_sort:
        raise _chart_configuration_error(
            "top_n_requires_value_sort",
            "Top N requires a selected measure or metric as its first sort",
            "query.sort.0",
        )
    if first.direction is not SortDirection.DESCENDING:
        raise _chart_configuration_error(
            "top_n_requires_descending_sort",
            "Top N requires descending value order",
            "query.sort.0.direction",
        )
    return [first, *sorts[1:]]


def _stable_sorts(
    component_type: ChartComponentType,
    query: ChartQuerySpec,
    sorts: list[QuerySort | MetricQuerySort],
) -> list[QuerySort | MetricQuerySort]:
    if not query.dimensions:
        return sorts
    needs_primary_tie_breaker = component_type == "ranking_table" or query.top_n is not None
    if query.series_dimension is None and not needs_primary_tie_breaker:
        return sorts

    primary = query.dimensions[0]
    stable_field_ids = {primary.field_id}
    if query.series_dimension is not None:
        stable_field_ids.add(query.series_dimension.field_id)
    retained = [
        sort
        for sort in sorts
        if not (
            isinstance(sort, QuerySort)
            and sort.aggregate is None
            and sort.field_id in stable_field_ids
        )
    ]
    retained.append(
        QuerySort(
            field_id=primary.field_id,
            time_grain=(TimeGrain(primary.time_grain) if primary.time_grain is not None else None),
            direction=SortDirection.ASCENDING,
        )
    )
    if query.series_dimension is not None:
        retained.append(
            QuerySort(
                field_id=query.series_dimension.field_id,
                direction=SortDirection.ASCENDING,
            )
        )
    return retained


def _measure_sort(
    query: ChartQuerySpec,
    index: int,
    direction: SortDirection,
) -> QuerySort | MetricQuerySort:
    if not query.measures:
        raise _chart_configuration_error(
            "chart_slot_invalid", "Value sorting requires a selected measure", "query.measures"
        )
    measure = query.measures[index]
    if isinstance(measure, ChartFieldMeasure):
        return QuerySort(
            field_id=measure.field_id,
            aggregate=measure.aggregate,
            direction=direction,
        )
    return MetricQuerySort(metric_id=measure.metric_version_id, direction=direction)


def _validate_series_cardinality(
    session: Session,
    *,
    principal: QueryPrincipal,
    compiled: CompiledDashboardChartQuery,
    timeout_seconds: float,
) -> int:
    primary = compiled.primary_dimension
    series_id = compiled.series_field_id
    series_maximum = compiled.series_maximum
    if primary is None or series_id is None or series_maximum is None:
        raise DashboardChartQueryError(
            "series_cardinality_not_resolved",
            "Series query cardinality context is incomplete",
            _CHART_ACTION,
        )
    primary_count = _group_cardinality(
        session,
        principal=principal,
        dataset_id=compiled.request.dataset_id,
        field_id=primary.field_id,
        time_grain=(TimeGrain(primary.time_grain) if primary.time_grain is not None else None),
        limit=compiled.request.limit,
        scoped_filters=compiled.scoped_filters,
        timeout_seconds=timeout_seconds,
    )
    series_count = _group_cardinality(
        session,
        principal=principal,
        dataset_id=compiled.request.dataset_id,
        field_id=series_id,
        time_grain=None,
        limit=series_maximum,
        scoped_filters=compiled.scoped_filters,
        timeout_seconds=timeout_seconds,
    )
    if series_count > series_maximum:
        raise DashboardChartQueryError(
            "series_cardinality_exceeded",
            "Series dimension cardinality exceeds max_series",
            "Reduce the series cardinality or increase max_series within its governed limit",
        )
    upper_bound = primary_count * series_count
    if upper_bound > compiled.request.limit:
        raise DashboardChartQueryError(
            "series_result_limit_exceeded",
            "Complete primary-by-series groups exceed the effective query limit",
            "Reduce the chart cardinality or increase query_limit",
        )
    return upper_bound


def _group_cardinality(
    session: Session,
    *,
    principal: QueryPrincipal,
    dataset_id: UUID,
    field_id: UUID,
    time_grain: TimeGrain | None,
    limit: int,
    scoped_filters: ResolvedScopedFilters,
    timeout_seconds: float,
) -> int:
    request = DatasetQueryRequest(
        dataset_id=dataset_id,
        selections=[
            QuerySelection(
                field_id=field_id,
                output_name="cardinality_key",
                time_grain=time_grain,
            ),
            QuerySelection(
                field_id=field_id,
                output_name="member_count",
                aggregate=AggregateFunction.COUNT,
            ),
        ],
        group_by=[field_id],
        limit=limit,
    )
    try:
        result = execute_dataset_query(
            session,
            principal=principal,
            request=request,
            timeout_seconds=timeout_seconds,
            scoped_filters=scoped_filters.filters,
        )
    except DatasetQueryError as exc:
        raise _chart_error_from_dataset(exc) from exc
    if result.truncated:
        return limit + 1
    return len(result.rows)


def _chart_result(
    compiled: CompiledDashboardChartQuery,
    result: DatasetQueryResult,
    *,
    warnings: tuple[ChartQueryWarning, ...],
) -> DashboardChartResult:
    aliases = tuple(column.query_alias for column in compiled.columns)
    if any(alias not in row for row in result.rows for alias in aliases):
        raise DashboardChartQueryError(
            "chart_result_invalid",
            "Chart result is missing a declared query output",
            _CHART_ACTION,
        )
    rows = tuple({alias: _canonical_value(row[alias]) for alias in aliases} for row in result.rows)
    return DashboardChartResult(
        request_id=uuid4(),
        component_id=compiled.component_id,
        columns=compiled.columns,
        rows=rows,
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
        dataset_version=result.dataset_version,
        metric_version_ids=result.metric_version_ids,
        source_batch_ids=result.source_batch_ids,
        resolved_filters=compiled.scoped_filters.evidence,
        warnings=warnings,
    )


def _canonical_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise DashboardChartQueryError(
                "chart_result_invalid", "Chart result contains a non-finite decimal", _CHART_ACTION
            )
        return format(value, "f")
    if isinstance(value, float):
        if not isfinite(value):
            raise DashboardChartQueryError(
                "chart_result_invalid", "Chart result contains a non-finite number", _CHART_ACTION
            )
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise DashboardChartQueryError(
        "chart_result_invalid", "Chart result contains an unsupported value", _CHART_ACTION
    )


def _required_field(
    fields: dict[UUID, ChartFieldResource],
    field_id: UUID,
    *,
    path: str,
) -> ChartFieldResource:
    field = fields.get(field_id)
    if field is None:
        raise _chart_configuration_error(
            "dataset_field_not_found", "Chart field was not found", path
        )
    return field


def _required_metric(
    metrics: dict[UUID, ChartMetricResource],
    metric_id: UUID,
    *,
    path: str,
) -> ChartMetricResource:
    metric = metrics.get(metric_id)
    if metric is None:
        raise _chart_configuration_error("metric_not_found", "Chart metric was not found", path)
    return metric


def _chart_configuration_error(
    code: str,
    message: str,
    path: str,
) -> DashboardChartQueryError:
    return DashboardChartQueryError(code, message, _CHART_ACTION, config_path=path)


def _chart_error_from_dataset(exc: DatasetQueryError) -> DashboardChartQueryError:
    return DashboardChartQueryError(exc.code, str(exc), exc.action)
