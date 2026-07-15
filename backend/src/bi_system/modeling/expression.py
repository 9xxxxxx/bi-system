from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictExpressionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComparisonOperator(StrEnum):
    EQUAL = "eq"
    NOT_EQUAL = "ne"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"


class SetOperator(StrEnum):
    IN = "in"
    NOT_IN = "not_in"


class TextOperator(StrEnum):
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"


class LogicalOperator(StrEnum):
    AND = "and"
    OR = "or"


type ScalarValue = str | int | float | Decimal | bool | date | datetime


class ComparisonPredicate(StrictExpressionModel):
    kind: Literal["comparison"]
    field_id: UUID
    operator: ComparisonOperator
    value: ScalarValue


class NullPredicate(StrictExpressionModel):
    kind: Literal["null"]
    field_id: UUID
    is_null: bool = True


class SetPredicate(StrictExpressionModel):
    kind: Literal["set"]
    field_id: UUID
    operator: SetOperator
    values: list[ScalarValue] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_values(self) -> SetPredicate:
        serialized = {(type(value).__name__, str(value)) for value in self.values}
        if len(serialized) != len(self.values):
            raise ValueError("Set predicate values must be unique")
        return self


class TextPredicate(StrictExpressionModel):
    kind: Literal["text"]
    field_id: UUID
    operator: TextOperator
    value: str = Field(min_length=1, max_length=1000)


type AtomicPredicate = Annotated[
    ComparisonPredicate | NullPredicate | SetPredicate | TextPredicate,
    Field(discriminator="kind"),
]


class LogicalPredicate(StrictExpressionModel):
    kind: Literal["logical"]
    operator: LogicalOperator
    predicates: list[AtomicPredicate] = Field(min_length=2, max_length=50)


type FilterExpression = Annotated[
    ComparisonPredicate | NullPredicate | SetPredicate | TextPredicate | LogicalPredicate,
    Field(discriminator="kind"),
]


def predicate_count(expression: FilterExpression | None) -> int:
    if expression is None:
        return 0
    if isinstance(expression, LogicalPredicate):
        return len(expression.predicates)
    return 1
