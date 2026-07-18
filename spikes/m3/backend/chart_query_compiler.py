from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from bi_system.modeling.contracts import (
    AggregateFunction,
    DatasetMetricSelection,
    DatasetQueryRequest,
    QuerySelection,
    QuerySort,
    SortDirection,
)
from bi_system.modeling.expression import FilterExpression, LogicalPredicate
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator


class StrictChartModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldMeasure(StrictChartModel):
    kind: Literal["field"]
    field_id: UUID
    aggregate: AggregateFunction


class MetricMeasure(StrictChartModel):
    kind: Literal["metric"]
    metric_version_id: UUID


Measure = Annotated[FieldMeasure | MetricMeasure, Field(discriminator="kind")]


class ChartSort(StrictChartModel):
    by: Literal["dimension", "value"]
    direction: SortDirection = SortDirection.ASCENDING
    value_index: int = Field(default=0, ge=0, le=9)


class SeriesDimension(StrictChartModel):
    field_id: UUID
    max_series: int = Field(ge=1, le=20)


class KpiChart(StrictChartModel):
    chart_type: Literal["kpi"]
    dataset_id: UUID
    value: Measure
    filter: FilterExpression | None = None


class DetailTableChart(StrictChartModel):
    chart_type: Literal["detail_table"]
    dataset_id: UUID
    columns: list[UUID] = Field(min_length=1, max_length=50)
    values: list[Measure] = Field(default_factory=list, max_length=50)
    sort_field_id: UUID | None = None
    sort_direction: SortDirection = SortDirection.ASCENDING
    filter: FilterExpression | None = None
    limit: int = Field(default=500, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_columns(self) -> DetailTableChart:
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Detail table columns must be unique")
        if self.sort_field_id is not None and self.sort_field_id not in self.columns:
            raise ValueError("Detail table sort field must be selected")
        return self


class CategoricalChart(StrictChartModel):
    chart_type: Literal["bar", "horizontal_bar", "line", "area"]
    dataset_id: UUID
    dimension_id: UUID
    values: list[Measure] = Field(min_length=1, max_length=10)
    series_dimension: SeriesDimension | None = None
    time_grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    sort: ChartSort | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)
    query_limit: int = Field(default=500, ge=1, le=10_000)
    filter: FilterExpression | None = None


class StackedBarChart(StrictChartModel):
    chart_type: Literal["stacked_bar"]
    dataset_id: UUID
    dimension_id: UUID
    values: list[Measure] = Field(min_length=1, max_length=10)
    series_dimension: SeriesDimension | None = None
    sort: ChartSort | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)
    query_limit: int = Field(default=500, ge=1, le=10_000)
    filter: FilterExpression | None = None

    @model_validator(mode="after")
    def validate_stacking_shape(self) -> StackedBarChart:
        if self.series_dimension is None and len(self.values) < 2:
            raise ValueError("Stacked bars require multiple values or one series dimension")
        if self.series_dimension is not None and len(self.values) != 1:
            raise ValueError("Series-dimension stacking requires exactly one value")
        return self


class RankingTableChart(StrictChartModel):
    chart_type: Literal["ranking_table"]
    dataset_id: UUID
    dimension_id: UUID
    value: Measure
    top_n: int = Field(default=10, ge=1, le=100)
    filter: FilterExpression | None = None


class PartToWholeChart(StrictChartModel):
    chart_type: Literal["pie", "donut"]
    dataset_id: UUID
    dimension_id: UUID
    value: Measure
    sort: ChartSort | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)
    filter: FilterExpression | None = None


ChartConfig = Annotated[
    KpiChart
    | DetailTableChart
    | CategoricalChart
    | StackedBarChart
    | RankingTableChart
    | PartToWholeChart,
    Field(discriminator="chart_type"),
]

_CHART_CONFIG_ADAPTER: TypeAdapter[ChartConfig] = TypeAdapter(ChartConfig)
_NUMERIC_DATA_TYPES = frozenset({"integer", "decimal", "float"})
_NUMERIC_AGGREGATES = frozenset(
    {
        AggregateFunction.SUM,
        AggregateFunction.AVERAGE,
        AggregateFunction.MINIMUM,
        AggregateFunction.MAXIMUM,
    }
)


@dataclass(frozen=True, slots=True)
class FieldMetadata:
    role: Literal["dimension", "measure"]
    data_type: Literal["string", "integer", "decimal", "float", "boolean", "date", "datetime"]


@dataclass(frozen=True, slots=True)
class ResourceCatalog:
    dataset_id: UUID
    fields: dict[UUID, FieldMetadata]
    metric_version_ids: frozenset[UUID]
    field_cardinalities: dict[UUID, int] | None = None


@dataclass(frozen=True, slots=True)
class SlotOutput:
    output_name: str
    slot: str
    resource_kind: Literal["field", "metric"]
    resource_id: UUID


@dataclass(frozen=True, slots=True)
class CompiledChartQuery:
    chart_type: str
    request: DatasetQueryRequest
    outputs: tuple[SlotOutput, ...]
    series_row_upper_bound: int | None = None


class ChartCompilationError(ValueError):
    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path

    def as_dict(self) -> dict[str, str]:
        result = {"code": self.code, "message": self.message}
        if self.path is not None:
            result["path"] = self.path
        return result


class ChartQueryCompiler:
    """Compile governed chart slots into the accepted M2 dataset query contract."""

    def compile(
        self,
        raw_config: ChartConfig | dict[str, object],
        catalog: ResourceCatalog,
    ) -> CompiledChartQuery:
        config = self._parse_config(raw_config)
        if config.dataset_id != catalog.dataset_id:
            raise ChartCompilationError(
                "dataset_not_resolved",
                "Chart dataset does not match the resolved resource catalog",
                path="dataset_id",
            )
        self._validate_filter(config.filter, catalog)
        series_row_upper_bound: int | None = None

        if isinstance(config, KpiChart):
            selections, metrics, outputs = self._compile_measures((config.value,), catalog)
            request = DatasetQueryRequest(
                dataset_id=config.dataset_id,
                selections=selections,
                metrics=metrics,
                filter=config.filter,
                limit=1,
            )
        elif isinstance(config, DetailTableChart):
            request, outputs = self._compile_detail_table(config, catalog)
        elif isinstance(config, RankingTableChart):
            request, outputs, series_row_upper_bound = self._compile_grouped(
                chart_type=config.chart_type,
                dataset_id=config.dataset_id,
                dimension_id=config.dimension_id,
                values=(config.value,),
                sort=ChartSort(by="value", direction=SortDirection.DESCENDING),
                top_n=config.top_n,
                series_dimension=None,
                time_grain=None,
                query_limit=500,
                filter_expression=config.filter,
                catalog=catalog,
            )
        elif isinstance(config, PartToWholeChart):
            request, outputs, series_row_upper_bound = self._compile_grouped(
                chart_type=config.chart_type,
                dataset_id=config.dataset_id,
                dimension_id=config.dimension_id,
                values=(config.value,),
                sort=config.sort,
                top_n=config.top_n,
                series_dimension=None,
                time_grain=None,
                query_limit=500,
                filter_expression=config.filter,
                catalog=catalog,
            )
        else:
            request, outputs, series_row_upper_bound = self._compile_grouped(
                chart_type=config.chart_type,
                dataset_id=config.dataset_id,
                dimension_id=config.dimension_id,
                values=tuple(config.values),
                sort=config.sort,
                top_n=config.top_n,
                series_dimension=config.series_dimension,
                time_grain=(config.time_grain if isinstance(config, CategoricalChart) else None),
                query_limit=config.query_limit,
                filter_expression=config.filter,
                catalog=catalog,
            )
        return CompiledChartQuery(
            chart_type=config.chart_type,
            request=request,
            outputs=outputs,
            series_row_upper_bound=series_row_upper_bound,
        )

    @staticmethod
    def validate_result_completeness(
        compiled: CompiledChartQuery,
        *,
        row_count: int,
        truncated: bool,
    ) -> None:
        upper_bound = compiled.series_row_upper_bound
        if upper_bound is None:
            return
        if truncated:
            raise ChartCompilationError(
                "series_result_truncated",
                "Truncated series results cannot preserve complete primary groups",
                path="result.truncated",
            )
        if row_count > upper_bound:
            raise ChartCompilationError(
                "series_cardinality_evidence_stale",
                "Series result exceeds the server-resolved cardinality upper bound",
                path="result.rows",
            )

    @staticmethod
    def _parse_config(raw_config: ChartConfig | dict[str, object]) -> ChartConfig:
        try:
            return _CHART_CONFIG_ADAPTER.validate_python(raw_config)
        except ValidationError as exc:
            first_error = exc.errors(include_url=False)[0]
            path = ".".join(str(item) for item in first_error["loc"])
            raise ChartCompilationError(
                "chart_config_invalid",
                str(first_error["msg"]),
                path=path or None,
            ) from exc

    def _compile_detail_table(
        self,
        config: DetailTableChart,
        catalog: ResourceCatalog,
    ) -> tuple[DatasetQueryRequest, tuple[SlotOutput, ...]]:
        selections: list[QuerySelection] = []
        outputs: list[SlotOutput] = []
        for index, field_id in enumerate(config.columns, start=1):
            self._field(field_id, catalog, path=f"columns.{index - 1}")
            output_name = f"column_{index}"
            selections.append(QuerySelection(field_id=field_id, output_name=output_name))
            outputs.append(
                SlotOutput(
                    output_name=output_name,
                    slot=f"columns.{index - 1}",
                    resource_kind="field",
                    resource_id=field_id,
                )
            )
        measure_selections, metrics, measure_outputs = self._compile_measures(
            tuple(config.values), catalog
        )
        selections.extend(measure_selections)
        outputs.extend(measure_outputs)
        order_by: list[QuerySort] = []
        if config.sort_field_id is not None:
            order_by.append(
                QuerySort(field_id=config.sort_field_id, direction=config.sort_direction)
            )
        return (
            DatasetQueryRequest(
                dataset_id=config.dataset_id,
                selections=selections,
                metrics=metrics,
                filter=config.filter,
                group_by=(config.columns if config.values else []),
                order_by=order_by,
                limit=config.limit,
            ),
            tuple(outputs),
        )

    def _compile_grouped(
        self,
        *,
        chart_type: str,
        dataset_id: UUID,
        dimension_id: UUID,
        values: tuple[Measure, ...],
        sort: ChartSort | None,
        top_n: int | None,
        series_dimension: SeriesDimension | None,
        time_grain: Literal["day", "week", "month", "quarter", "year"] | None,
        query_limit: int,
        filter_expression: FilterExpression | None,
        catalog: ResourceCatalog,
    ) -> tuple[DatasetQueryRequest, tuple[SlotOutput, ...], int | None]:
        if time_grain is not None:
            raise ChartCompilationError(
                "time_grain_not_supported",
                "M2 group_by cannot express a governed time-grain bucket",
                path="time_grain",
            )
        dimension = self._field(dimension_id, catalog, path="dimension_id")
        if dimension.role != "dimension":
            raise ChartCompilationError(
                "invalid_dimension_role",
                "Dimension slot requires a dimension field",
                path="dimension_id",
            )
        selections, metrics, measure_outputs = self._compile_measures(values, catalog)
        selections.insert(
            0,
            QuerySelection(field_id=dimension_id, output_name="dimension"),
        )
        outputs = (
            SlotOutput(
                output_name="dimension",
                slot="dimension",
                resource_kind="field",
                resource_id=dimension_id,
            ),
            *measure_outputs,
        )
        group_by = [dimension_id]
        series_id: UUID | None = None
        series_row_upper_bound: int | None = None
        if series_dimension is not None:
            if top_n is not None:
                raise ChartCompilationError(
                    "series_top_n_not_supported",
                    "M3 rejects series-dimension Top N because it can produce partial groups",
                    path="top_n",
                )
            series = self._field(
                series_dimension.field_id,
                catalog,
                path="series_dimension.field_id",
            )
            if series.role != "dimension":
                raise ChartCompilationError(
                    "invalid_series_dimension_role",
                    "Series dimension slot requires a dimension field",
                    path="series_dimension.field_id",
                )
            if series_dimension.field_id == dimension_id:
                raise ChartCompilationError(
                    "duplicate_dimension",
                    "Primary and series dimensions must be different fields",
                    path="series_dimension.field_id",
                )
            cardinalities = catalog.field_cardinalities
            if cardinalities is None or dimension_id not in cardinalities:
                raise ChartCompilationError(
                    "series_cardinality_not_resolved",
                    "Series queries require server-resolved primary-dimension cardinality",
                    path="dimension_id",
                )
            if series_dimension.field_id not in cardinalities:
                raise ChartCompilationError(
                    "series_cardinality_not_resolved",
                    "Series queries require server-resolved series-dimension cardinality",
                    path="series_dimension.field_id",
                )
            primary_cardinality = cardinalities[dimension_id]
            series_cardinality = cardinalities[series_dimension.field_id]
            if primary_cardinality < 0 or series_cardinality < 0:
                raise ChartCompilationError(
                    "series_cardinality_invalid",
                    "Resolved dimension cardinalities must be non-negative",
                    path="field_cardinalities",
                )
            if series_cardinality > series_dimension.max_series:
                raise ChartCompilationError(
                    "series_cardinality_exceeded",
                    "Series dimension cardinality exceeds the configured bound",
                    path="series_dimension.max_series",
                )
            series_row_upper_bound = primary_cardinality * series_cardinality
            if series_row_upper_bound > query_limit:
                raise ChartCompilationError(
                    "series_result_limit_exceeded",
                    "Complete primary-by-series groups exceed the effective query limit",
                    path="query_limit",
                )
            series_id = series_dimension.field_id
            selections.insert(
                1,
                QuerySelection(field_id=series_id, output_name="series"),
            )
            outputs = (
                outputs[0],
                SlotOutput(
                    output_name="series",
                    slot="series_dimension",
                    resource_kind="field",
                    resource_id=series_id,
                ),
                *outputs[1:],
            )
            group_by.append(series_id)

        effective_sort = sort
        if top_n is not None:
            if sort is not None and sort.by != "value":
                raise ChartCompilationError(
                    "top_n_requires_value_sort",
                    "Top N must sort by a selected value",
                    path="sort.by",
                )
            if sort is not None and sort.direction is not SortDirection.DESCENDING:
                raise ChartCompilationError(
                    "top_n_requires_descending_sort",
                    "Top N must use descending value order",
                    path="sort.direction",
                )
            effective_sort = sort or ChartSort(
                by="value",
                direction=SortDirection.DESCENDING,
            )
        order_by = self._compile_sort(effective_sort, values, dimension_id)
        if top_n is not None:
            order_by.append(QuerySort(field_id=dimension_id, direction=SortDirection.ASCENDING))
        if series_id is not None:
            if not order_by:
                order_by.append(QuerySort(field_id=dimension_id, direction=SortDirection.ASCENDING))
            order_by.append(QuerySort(field_id=series_id, direction=SortDirection.ASCENDING))
        limit = top_n if top_n is not None else query_limit
        return (
            DatasetQueryRequest(
                dataset_id=dataset_id,
                selections=selections,
                metrics=metrics,
                filter=filter_expression,
                group_by=group_by,
                order_by=order_by,
                limit=limit,
            ),
            outputs,
            series_row_upper_bound,
        )

    def _compile_measures(
        self,
        values: tuple[Measure, ...],
        catalog: ResourceCatalog,
    ) -> tuple[list[QuerySelection], list[DatasetMetricSelection], tuple[SlotOutput, ...]]:
        selections: list[QuerySelection] = []
        metrics: list[DatasetMetricSelection] = []
        outputs: list[SlotOutput] = []
        seen: set[tuple[str, UUID, AggregateFunction | None]] = set()
        for index, value in enumerate(values, start=1):
            output_name = f"value_{index}"
            path = f"values.{index - 1}" if len(values) > 1 else "value"
            if isinstance(value, FieldMeasure):
                metadata = self._field(value.field_id, catalog, path=f"{path}.field_id")
                if value.aggregate in _NUMERIC_AGGREGATES and (
                    metadata.data_type not in _NUMERIC_DATA_TYPES
                ):
                    raise ChartCompilationError(
                        "invalid_aggregate_type",
                        f"Aggregate {value.aggregate.value} requires a numeric field",
                        path=f"{path}.aggregate",
                    )
                signature = ("field", value.field_id, value.aggregate)
                selections.append(
                    QuerySelection(
                        field_id=value.field_id,
                        output_name=output_name,
                        aggregate=value.aggregate,
                    )
                )
                resource_kind: Literal["field", "metric"] = "field"
                resource_id = value.field_id
            else:
                if value.metric_version_id not in catalog.metric_version_ids:
                    raise ChartCompilationError(
                        "metric_version_not_resolved",
                        "Metric version is not present in the resolved resource catalog",
                        path=f"{path}.metric_version_id",
                    )
                signature = ("metric", value.metric_version_id, None)
                metrics.append(
                    DatasetMetricSelection(
                        metric_id=value.metric_version_id,
                        output_name=output_name,
                    )
                )
                resource_kind = "metric"
                resource_id = value.metric_version_id
            if signature in seen:
                raise ChartCompilationError(
                    "duplicate_value",
                    "Value slots must reference unique resource and aggregation pairs",
                    path=path,
                )
            seen.add(signature)
            outputs.append(
                SlotOutput(
                    output_name=output_name,
                    slot=path,
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                )
            )
        return selections, metrics, tuple(outputs)

    @staticmethod
    def _compile_sort(
        sort: ChartSort | None,
        values: tuple[Measure, ...],
        dimension_id: UUID,
    ) -> list[QuerySort]:
        if sort is None:
            return []
        if sort.by == "dimension":
            return [QuerySort(field_id=dimension_id, direction=sort.direction)]
        if sort.value_index >= len(values):
            raise ChartCompilationError(
                "sort_value_not_selected",
                "Sort value index does not reference a selected value",
                path="sort.value_index",
            )
        value = values[sort.value_index]
        if isinstance(value, MetricMeasure):
            raise ChartCompilationError(
                "metric_sort_not_supported",
                "M2 order_by cannot reference a versioned metric",
                path="sort",
            )
        return [
            QuerySort(
                field_id=value.field_id,
                aggregate=value.aggregate,
                direction=sort.direction,
            )
        ]

    @staticmethod
    def _field(field_id: UUID, catalog: ResourceCatalog, *, path: str) -> FieldMetadata:
        metadata = catalog.fields.get(field_id)
        if metadata is None:
            raise ChartCompilationError(
                "field_not_resolved",
                "Field is not present in the resolved resource catalog",
                path=path,
            )
        return metadata

    def _validate_filter(
        self,
        expression: FilterExpression | None,
        catalog: ResourceCatalog,
    ) -> None:
        if expression is None:
            return
        predicates = (
            expression.predicates if isinstance(expression, LogicalPredicate) else (expression,)
        )
        for index, predicate in enumerate(predicates):
            self._field(predicate.field_id, catalog, path=f"filter.predicates.{index}.field_id")
