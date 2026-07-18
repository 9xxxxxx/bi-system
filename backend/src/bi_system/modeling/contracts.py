from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bi_system.modeling.expression import FilterExpression, predicate_count


class StrictQueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AggregateFunction(StrEnum):
    SUM = "sum"
    AVERAGE = "avg"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    MINIMUM = "min"
    MAXIMUM = "max"


class SortDirection(StrEnum):
    ASCENDING = "asc"
    DESCENDING = "desc"


class TimeGrain(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class QuerySelection(StrictQueryModel):
    field_id: UUID
    output_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    aggregate: AggregateFunction | None = None
    time_grain: TimeGrain | None = None

    @model_validator(mode="after")
    def validate_expression(self) -> QuerySelection:
        if self.aggregate is not None and self.time_grain is not None:
            raise ValueError("Aggregate selections cannot also use a time grain")
        return self


class QuerySort(StrictQueryModel):
    kind: Literal["field"] = "field"
    field_id: UUID
    aggregate: AggregateFunction | None = None
    time_grain: TimeGrain | None = None
    direction: SortDirection = SortDirection.ASCENDING

    @model_validator(mode="after")
    def validate_expression(self) -> QuerySort:
        if self.aggregate is not None and self.time_grain is not None:
            raise ValueError("Aggregate sorts cannot also use a time grain")
        return self


class MetricQuerySort(StrictQueryModel):
    kind: Literal["metric"] = "metric"
    metric_id: UUID
    direction: SortDirection = SortDirection.ASCENDING


DatasetQuerySort = QuerySort | MetricQuerySort


class DatasetMetricSelection(StrictQueryModel):
    metric_id: UUID
    output_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")


class QueryRequest(StrictQueryModel):
    source_id: UUID
    selections: list[QuerySelection] = Field(min_length=1, max_length=100)
    filter: FilterExpression | None = None
    group_by: list[UUID] = Field(default_factory=list, max_length=20)
    order_by: list[QuerySort] = Field(default_factory=list, max_length=10)
    limit: Annotated[int, Field(ge=1, le=10_000)] = 500

    @field_validator("group_by")
    @classmethod
    def validate_unique_group_fields(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("Group fields must be unique")
        return values

    @model_validator(mode="after")
    def validate_query_shape(self) -> QueryRequest:
        output_names = [selection.output_name for selection in self.selections]
        if len(set(output_names)) != len(output_names):
            raise ValueError("Selection output names must be unique")

        signatures = [
            (selection.field_id, selection.aggregate, selection.time_grain)
            for selection in self.selections
        ]
        if len(set(signatures)) != len(signatures):
            raise ValueError("Selection field and aggregate pairs must be unique")

        selected_signatures = set(signatures)
        missing_sorts = [
            sort
            for sort in self.order_by
            if (sort.field_id, sort.aggregate, sort.time_grain) not in selected_signatures
        ]
        if missing_sorts:
            raise ValueError("Sort expressions must also be selected")

        has_aggregate = any(selection.aggregate is not None for selection in self.selections)
        non_aggregate_fields = {
            selection.field_id for selection in self.selections if selection.aggregate is None
        }
        if has_aggregate and non_aggregate_fields != set(self.group_by):
            raise ValueError("Non-aggregate selections must exactly match group fields")
        if not has_aggregate and self.group_by:
            raise ValueError("Group fields require at least one aggregate selection")
        if predicate_count(self.filter) > 50:
            raise ValueError("Query has too many filter predicates")
        return self


class DatasetQueryRequest(StrictQueryModel):
    dataset_id: UUID
    selections: list[QuerySelection] = Field(default_factory=list, max_length=100)
    metrics: list[DatasetMetricSelection] = Field(default_factory=list, max_length=50)
    filter: FilterExpression | None = None
    group_by: list[UUID] = Field(default_factory=list, max_length=20)
    order_by: list[DatasetQuerySort] = Field(default_factory=list, max_length=10)
    limit: Annotated[int, Field(ge=1, le=10_000)] = 500

    @field_validator("group_by")
    @classmethod
    def validate_unique_group_fields(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("Group fields must be unique")
        return values

    @model_validator(mode="after")
    def validate_query_shape(self) -> DatasetQueryRequest:
        if not self.selections and not self.metrics:
            raise ValueError("Dataset query must select at least one field or metric")
        if not self.metrics:
            field_sorts = [sort for sort in self.order_by if isinstance(sort, QuerySort)]
            if len(field_sorts) != len(self.order_by):
                raise ValueError("Metric sorts require selected metrics")
            QueryRequest(
                source_id=self.dataset_id,
                selections=self.selections,
                filter=self.filter,
                group_by=self.group_by,
                order_by=field_sorts,
                limit=self.limit,
            )
            return self

        if len(self.selections) + len(self.metrics) > 100:
            raise ValueError("Dataset query may return at most 100 outputs")

        output_names = [selection.output_name for selection in self.selections]
        output_names.extend(metric.output_name for metric in self.metrics)
        if len(set(output_names)) != len(output_names):
            raise ValueError("Dataset query output names must be unique")
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("Dataset query metrics must be unique")

        signatures = [
            (selection.field_id, selection.aggregate, selection.time_grain)
            for selection in self.selections
        ]
        if len(set(signatures)) != len(signatures):
            raise ValueError("Selection field and aggregate pairs must be unique")
        selected_signatures = set(signatures)
        selected_metric_ids = set(metric_ids)
        if any(
            (
                isinstance(sort, QuerySort)
                and (sort.field_id, sort.aggregate, sort.time_grain) not in selected_signatures
            )
            or (isinstance(sort, MetricQuerySort) and sort.metric_id not in selected_metric_ids)
            for sort in self.order_by
        ):
            raise ValueError("Sort expressions must also be selected")

        non_aggregate_fields = {
            selection.field_id for selection in self.selections if selection.aggregate is None
        }
        if non_aggregate_fields != set(self.group_by):
            raise ValueError("Non-aggregate selections must exactly match group fields")
        if predicate_count(self.filter) > 50:
            raise ValueError("Query has too many filter predicates")
        return self

    def for_source(self, source_id: UUID) -> QueryRequest:
        field_sorts = [sort for sort in self.order_by if isinstance(sort, QuerySort)]
        if len(field_sorts) != len(self.order_by):
            raise ValueError("Metric sorts require selected metrics")
        return QueryRequest(
            source_id=source_id,
            selections=self.selections,
            filter=self.filter,
            group_by=self.group_by,
            order_by=field_sorts,
            limit=self.limit,
        )
