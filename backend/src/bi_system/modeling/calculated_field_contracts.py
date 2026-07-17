from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bi_system.modeling.expression import (
    FilterExpression,
    LogicalPredicate,
    predicate_count,
)


class StrictCalculatedFieldModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalculatedFieldReference(StrictCalculatedFieldModel):
    op: Literal["field"]
    field_id: UUID


class CalculatedLiteral(StrictCalculatedFieldModel):
    op: Literal["literal"]
    value: bool | int | Decimal | date | datetime | str | None

    @field_validator("value")
    @classmethod
    def validate_finite_value(
        cls,
        value: bool | int | Decimal | date | datetime | str | None,
    ) -> bool | int | Decimal | date | datetime | str | None:
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("Calculated field literals must be finite")
        return value


class CalculatedBinary(StrictCalculatedFieldModel):
    op: Literal["add", "subtract", "multiply"]
    left: CalculatedExpression
    right: CalculatedExpression


class CalculatedSafeDivide(StrictCalculatedFieldModel):
    op: Literal["safe_divide"]
    numerator: CalculatedExpression
    denominator: CalculatedExpression
    fallback: int | Decimal | None = None

    @field_validator("fallback")
    @classmethod
    def validate_finite_fallback(cls, value: int | Decimal | None) -> int | Decimal | None:
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("Safe division fallback must be finite")
        return value


class CalculatedCase(StrictCalculatedFieldModel):
    op: Literal["case"]
    when: FilterExpression
    then: CalculatedExpression
    else_: CalculatedExpression = Field(alias="else", serialization_alias="else")


CalculatedExpression = Annotated[
    CalculatedFieldReference
    | CalculatedLiteral
    | CalculatedBinary
    | CalculatedSafeDivide
    | CalculatedCase,
    Field(discriminator="op"),
]

CalculatedBinary.model_rebuild()
CalculatedSafeDivide.model_rebuild()
CalculatedCase.model_rebuild()


class CalculatedExpressionPayload(StrictCalculatedFieldModel):
    expression: CalculatedExpression


class CreateCalculatedField(StrictCalculatedFieldModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    label: str = Field(min_length=1, max_length=128)
    role: Literal["dimension", "measure"]
    data_type: Literal["string", "integer", "decimal", "boolean", "date", "datetime"]
    hidden: bool = False
    expression: CalculatedExpression

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Calculated field label must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_expression_complexity(self) -> CreateCalculatedField:
        node_count, depth = calculated_expression_statistics(self.expression)
        if node_count > 50:
            raise ValueError("Calculated field expression may contain at most 50 nodes")
        if depth > 8:
            raise ValueError("Calculated field expression may be at most 8 levels deep")
        return self


def parse_calculated_expression(value: object) -> CalculatedExpression:
    return CalculatedExpressionPayload.model_validate({"expression": value}).expression


def calculated_expression_statistics(
    expression: CalculatedExpression,
    *,
    depth: int = 1,
) -> tuple[int, int]:
    if isinstance(expression, (CalculatedFieldReference, CalculatedLiteral)):
        return 1, depth
    if isinstance(expression, CalculatedBinary):
        children = (expression.left, expression.right)
        condition_nodes = 0
    elif isinstance(expression, CalculatedSafeDivide):
        children = (expression.numerator, expression.denominator)
        condition_nodes = 0
    else:
        children = (expression.then, expression.else_)
        condition_nodes = predicate_count(expression.when)
    child_statistics = [
        calculated_expression_statistics(child, depth=depth + 1) for child in children
    ]
    return (
        1 + condition_nodes + sum(item[0] for item in child_statistics),
        max(item[1] for item in child_statistics),
    )


def calculated_expression_field_ids(expression: CalculatedExpression) -> frozenset[UUID]:
    field_ids: set[UUID] = set()
    if isinstance(expression, CalculatedFieldReference):
        field_ids.add(expression.field_id)
    elif isinstance(expression, CalculatedBinary):
        field_ids.update(calculated_expression_field_ids(expression.left))
        field_ids.update(calculated_expression_field_ids(expression.right))
    elif isinstance(expression, CalculatedSafeDivide):
        field_ids.update(calculated_expression_field_ids(expression.numerator))
        field_ids.update(calculated_expression_field_ids(expression.denominator))
    elif isinstance(expression, CalculatedCase):
        field_ids.update(_filter_field_ids(expression.when))
        field_ids.update(calculated_expression_field_ids(expression.then))
        field_ids.update(calculated_expression_field_ids(expression.else_))
    return frozenset(field_ids)


def rewrite_calculated_expression_fields(
    expression: CalculatedExpression,
    field_id_map: dict[UUID, UUID],
) -> CalculatedExpression:
    if isinstance(expression, CalculatedFieldReference):
        return expression.model_copy(
            update={"field_id": _mapped_id(expression.field_id, field_id_map)}
        )
    if isinstance(expression, CalculatedLiteral):
        return expression
    if isinstance(expression, CalculatedBinary):
        return expression.model_copy(
            update={
                "left": rewrite_calculated_expression_fields(expression.left, field_id_map),
                "right": rewrite_calculated_expression_fields(expression.right, field_id_map),
            }
        )
    if isinstance(expression, CalculatedSafeDivide):
        return expression.model_copy(
            update={
                "numerator": rewrite_calculated_expression_fields(
                    expression.numerator, field_id_map
                ),
                "denominator": rewrite_calculated_expression_fields(
                    expression.denominator, field_id_map
                ),
            }
        )
    return expression.model_copy(
        update={
            "when": _rewrite_filter_fields(expression.when, field_id_map),
            "then": rewrite_calculated_expression_fields(expression.then, field_id_map),
            "else_": rewrite_calculated_expression_fields(expression.else_, field_id_map),
        }
    )


def _filter_field_ids(expression: FilterExpression) -> set[UUID]:
    predicates = (
        expression.predicates if isinstance(expression, LogicalPredicate) else (expression,)
    )
    return {predicate.field_id for predicate in predicates}


def _rewrite_filter_fields(
    expression: FilterExpression,
    field_id_map: dict[UUID, UUID],
) -> FilterExpression:
    if isinstance(expression, LogicalPredicate):
        return expression.model_copy(
            update={
                "predicates": [
                    predicate.model_copy(
                        update={"field_id": _mapped_id(predicate.field_id, field_id_map)}
                    )
                    for predicate in expression.predicates
                ]
            }
        )
    return expression.model_copy(update={"field_id": _mapped_id(expression.field_id, field_id_map)})


def _mapped_id(field_id: UUID, field_id_map: dict[UUID, UUID]) -> UUID:
    mapped = field_id_map.get(field_id)
    if mapped is None:
        raise ValueError(f"Calculated expression references missing field {field_id}")
    return mapped
