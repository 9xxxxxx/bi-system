from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bi_system.dashboards.filters import AbsoluteDateRangeFilter, RelativeDateFilter
from bi_system.modeling.contracts import AggregateFunction, SortDirection
from bi_system.modeling.expression import FilterExpression

type ChartComponentType = Literal[
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
]
type TimeGrain = Literal["day", "week", "month", "quarter", "year"]


class StrictChartModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChartDimension(StrictChartModel):
    field_id: UUID
    slot_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    time_grain: TimeGrain | None = None


class ChartSeriesDimension(StrictChartModel):
    field_id: UUID
    slot_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    max_series: int = Field(ge=1, le=20)


class ChartFieldMeasure(StrictChartModel):
    kind: Literal["field"]
    field_id: UUID
    aggregate: AggregateFunction
    slot_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")


class ChartMetricMeasure(StrictChartModel):
    kind: Literal["metric"]
    metric_version_id: UUID
    slot_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")


type ChartMeasure = Annotated[
    ChartFieldMeasure | ChartMetricMeasure,
    Field(discriminator="kind"),
]


class ChartFieldSort(StrictChartModel):
    kind: Literal["field"]
    field_id: UUID
    aggregate: AggregateFunction | None = None
    direction: SortDirection = SortDirection.ASCENDING


class ChartMetricSort(StrictChartModel):
    kind: Literal["metric"]
    metric_version_id: UUID
    direction: SortDirection = SortDirection.ASCENDING


type ChartSort = Annotated[ChartFieldSort | ChartMetricSort, Field(discriminator="kind")]
type ChartFilterInput = (
    FilterExpression | RelativeDateFilter | AbsoluteDateRangeFilter | dict[str, object]
)


class ChartQuerySpec(StrictChartModel):
    dataset_id: UUID
    dimensions: list[ChartDimension] = Field(default_factory=list, max_length=20)
    series_dimension: ChartSeriesDimension | None = None
    measures: list[ChartMeasure] = Field(default_factory=list, max_length=50)
    sort: list[ChartSort] = Field(default_factory=list, max_length=10)
    top_n: int | None = Field(default=None, ge=1, le=100)
    query_limit: int = Field(default=500, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_query_shape(self) -> ChartQuerySpec:
        slot_keys = [dimension.slot_key for dimension in self.dimensions]
        slot_keys.extend(measure.slot_key for measure in self.measures)
        if self.series_dimension is not None:
            slot_keys.append(self.series_dimension.slot_key)
        if len(set(slot_keys)) != len(slot_keys):
            raise ValueError("Chart slot_key values must be unique")
        if len(self.dimensions) + len(self.measures) + (self.series_dimension is not None) > 100:
            raise ValueError("Chart query may return at most 100 outputs")
        if self.series_dimension is not None:
            dimension_ids = {dimension.field_id for dimension in self.dimensions}
            if self.series_dimension.field_id in dimension_ids:
                raise ValueError("Chart series dimension must differ from primary dimensions")
            if self.top_n is not None:
                raise ValueError("Chart series dimension cannot be combined with Top N")
        self._validate_sort_targets()
        return self

    def _validate_sort_targets(self) -> None:
        field_signatures: set[tuple[UUID, AggregateFunction | None]] = {
            (dimension.field_id, None) for dimension in self.dimensions
        }
        if self.series_dimension is not None:
            field_signatures.add((self.series_dimension.field_id, None))
        field_signatures.update(
            (measure.field_id, measure.aggregate)
            for measure in self.measures
            if isinstance(measure, ChartFieldMeasure)
        )
        metric_ids = {
            measure.metric_version_id
            for measure in self.measures
            if isinstance(measure, ChartMetricMeasure)
        }
        for sort in self.sort:
            if isinstance(sort, ChartFieldSort):
                if (sort.field_id, sort.aggregate) not in field_signatures:
                    raise ValueError("Chart field sort must reference a selected output")
            elif sort.metric_version_id not in metric_ids:
                raise ValueError("Chart metric sort must reference a selected metric")


class ChartComponentConfig(StrictChartModel):
    schema_version: Literal[1]
    title: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    query: ChartQuerySpec
    component_filter: ChartFilterInput | None = None
    presentation: dict[str, object] = Field(default_factory=dict)

    @field_validator("presentation")
    @classmethod
    def reject_executable_presentation(
        cls,
        value: dict[str, object],
    ) -> dict[str, object]:
        forbidden = _find_forbidden_key(value)
        if forbidden is not None:
            raise ValueError(f"Chart presentation contains forbidden key {forbidden!r}")
        return value


class RuntimeChartFilterScopes(StrictChartModel):
    global_filter: ChartFilterInput | None = None
    page_filter: ChartFilterInput | None = None
    component_filter: ChartFilterInput | None = None


class PreviewChartComponent(StrictChartModel):
    component_id: UUID
    page_id: UUID
    component_type: ChartComponentType
    config_version: Literal[1]
    config: ChartComponentConfig

    @model_validator(mode="after")
    def validate_component_slots(self) -> PreviewChartComponent:
        _validate_component_query(self.component_type, self.config.query)
        return self


class DashboardChartQueryRequest(StrictChartModel):
    dashboard_id: UUID
    dashboard_version_id: UUID
    page_id: UUID
    component_id: UUID
    preview_component: PreviewChartComponent | None = None
    runtime_filters: RuntimeChartFilterScopes | None = None

    @model_validator(mode="after")
    def validate_preview_context(self) -> DashboardChartQueryRequest:
        preview = self.preview_component
        if preview is not None and (
            preview.component_id != self.component_id or preview.page_id != self.page_id
        ):
            raise ValueError("Preview component identifiers must match the request context")
        return self


def _find_forbidden_key(value: object) -> str | None:
    forbidden_keys = {
        "sql",
        "raw_sql",
        "table_name",
        "column_name",
        "physical_table_name",
        "physical_column_name",
        "function",
    }
    if isinstance(value, dict):
        for key, nested in cast(dict[object, object], value).items():
            if isinstance(key, str) and key.lower() in forbidden_keys:
                return key
            found = _find_forbidden_key(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in cast(list[object], value):
            found = _find_forbidden_key(nested)
            if found is not None:
                return found
    return None


def _validate_component_query(
    component_type: ChartComponentType,
    query: ChartQuerySpec,
) -> None:
    dimension_count = len(query.dimensions)
    measure_count = len(query.measures)
    has_series = query.series_dimension is not None
    if has_series and component_type not in {
        "bar",
        "horizontal_bar",
        "stacked_bar",
        "line",
        "area",
    }:
        raise ValueError(f"{component_type} does not support a series dimension")
    if component_type == "kpi":
        _require_counts(
            component_type, dimension_count, measure_count, dimensions=0, measures=(1, 1)
        )
    elif component_type == "trend_indicator":
        _require_counts(
            component_type, dimension_count, measure_count, dimensions=1, measures=(1, 1)
        )
        if query.dimensions[0].time_grain is None:
            raise ValueError("Trend indicator requires a governed time grain")
    elif component_type == "target_progress":
        _require_counts(
            component_type, dimension_count, measure_count, dimensions=0, measures=(1, 2)
        )
    elif component_type == "detail_table":
        if not 1 <= dimension_count + measure_count <= 100 or has_series:
            raise ValueError("Detail table requires 1-100 fields/measures and no series dimension")
    elif component_type in {"ranking_table", "bar", "horizontal_bar", "line", "area"}:
        _require_counts(
            component_type, dimension_count, measure_count, dimensions=1, measures=(1, 50)
        )
    elif component_type == "stacked_bar":
        _require_counts(
            component_type, dimension_count, measure_count, dimensions=1, measures=(1, 50)
        )
        if has_series and measure_count != 1:
            raise ValueError("Series-dimension stacked bar requires exactly one measure")
        if not has_series and measure_count < 2:
            raise ValueError("Stacked bar requires a series dimension or multiple measures")
    else:
        _require_counts(
            component_type, dimension_count, measure_count, dimensions=1, measures=(1, 1)
        )
        if has_series:
            raise ValueError("Pie and donut charts do not support a series dimension")


def _require_counts(
    component_type: str,
    dimension_count: int,
    measure_count: int,
    *,
    dimensions: int,
    measures: tuple[int, int],
) -> None:
    if dimension_count != dimensions or not measures[0] <= measure_count <= measures[1]:
        raise ValueError(
            f"{component_type} requires {dimensions} dimensions and "
            f"{measures[0]}-{measures[1]} measures"
        )
