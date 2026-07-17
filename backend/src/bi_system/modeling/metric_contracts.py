from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bi_system.modeling.contracts import AggregateFunction


class StrictMetricModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricLiteral(StrictMetricModel):
    op: Literal["literal"]
    value: Decimal

    @field_validator("value")
    @classmethod
    def validate_finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("Metric literals must be finite")
        return value


class MetricAggregate(StrictMetricModel):
    op: Literal["aggregate"]
    function: AggregateFunction
    field_id: UUID


class MetricBinary(StrictMetricModel):
    op: Literal["add", "subtract", "multiply"]
    left: MetricExpression
    right: MetricExpression


class MetricSafeDivide(StrictMetricModel):
    op: Literal["safe_divide"]
    numerator: MetricExpression
    denominator: MetricExpression
    fallback: Decimal | None = None

    @field_validator("fallback")
    @classmethod
    def validate_finite_fallback(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("Safe division fallback must be finite")
        return value


MetricExpression = Annotated[
    MetricLiteral | MetricAggregate | MetricBinary | MetricSafeDivide,
    Field(discriminator="op"),
]

MetricBinary.model_rebuild()
MetricSafeDivide.model_rebuild()


class MetricFormulaPayload(StrictMetricModel):
    formula: MetricExpression


def parse_metric_expression(value: object) -> MetricExpression:
    return MetricFormulaPayload.model_validate({"formula": value}).formula


class MetricDefinitionMixin(StrictMetricModel):
    @staticmethod
    def validate_formula_complexity(formula: MetricExpression) -> None:
        node_count, depth, aggregate_count = _formula_statistics(formula)
        if node_count > 50:
            raise ValueError("Metric formula may contain at most 50 nodes")
        if depth > 8:
            raise ValueError("Metric formula may be at most 8 levels deep")
        if aggregate_count == 0:
            raise ValueError("Metric formula must contain at least one aggregate")

    @staticmethod
    def validate_dimensions(dimension_field_ids: list[UUID]) -> None:
        if len(set(dimension_field_ids)) != len(dimension_field_ids):
            raise ValueError("Metric dimensions must be unique")


def metric_field_ids(formula: MetricExpression) -> frozenset[UUID]:
    if isinstance(formula, MetricAggregate):
        return frozenset({formula.field_id})
    if isinstance(formula, MetricLiteral):
        return frozenset()
    if isinstance(formula, MetricBinary):
        children = (formula.left, formula.right)
    else:
        children = (formula.numerator, formula.denominator)
    field_ids: set[UUID] = set()
    for child in children:
        field_ids.update(metric_field_ids(child))
    return frozenset(field_ids)


class CreateMetric(MetricDefinitionMixin):
    dataset_id: UUID
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    formula: MetricExpression
    unit: str | None = Field(default=None, max_length=32)
    dimension_field_ids: list[UUID] = Field(default_factory=list, max_length=100)
    status: Literal["draft", "active"] = "draft"

    @field_validator("name", "description")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Metric text must not be blank")
        return stripped

    @field_validator("unit")
    @classmethod
    def strip_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_definition(self) -> CreateMetric:
        self.validate_formula_complexity(self.formula)
        self.validate_dimensions(self.dimension_field_ids)
        return self


class CreateMetricVersion(MetricDefinitionMixin):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    formula: MetricExpression | None = None
    unit: str | None = Field(default=None, max_length=32)
    dimension_field_ids: list[UUID] | None = Field(default=None, max_length=100)
    status: Literal["draft", "active"] = "draft"

    @field_validator("name", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Metric text must not be blank")
        return stripped

    @field_validator("unit")
    @classmethod
    def strip_optional_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_definition(self) -> CreateMetricVersion:
        if self.formula is not None:
            self.validate_formula_complexity(self.formula)
        if self.dimension_field_ids is not None:
            self.validate_dimensions(self.dimension_field_ids)
        return self


def _formula_statistics(formula: MetricExpression, *, depth: int = 1) -> tuple[int, int, int]:
    if isinstance(formula, MetricAggregate):
        return 1, depth, 1
    if isinstance(formula, MetricLiteral):
        return 1, depth, 0
    if isinstance(formula, MetricBinary):
        children = (formula.left, formula.right)
    else:
        children = (formula.numerator, formula.denominator)
    statistics = [_formula_statistics(child, depth=depth + 1) for child in children]
    return (
        1 + sum(item[0] for item in statistics),
        max(item[1] for item in statistics),
        sum(item[2] for item in statistics),
    )
