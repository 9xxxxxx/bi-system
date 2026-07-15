from __future__ import annotations

from enum import StrEnum
from typing import Annotated
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


class QuerySelection(StrictQueryModel):
    field_id: UUID
    output_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    aggregate: AggregateFunction | None = None


class QuerySort(StrictQueryModel):
    field_id: UUID
    aggregate: AggregateFunction | None = None
    direction: SortDirection = SortDirection.ASCENDING


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

        signatures = [(selection.field_id, selection.aggregate) for selection in self.selections]
        if len(set(signatures)) != len(signatures):
            raise ValueError("Selection field and aggregate pairs must be unique")

        selected_signatures = set(signatures)
        missing_sorts = [
            sort
            for sort in self.order_by
            if (sort.field_id, sort.aggregate) not in selected_signatures
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
