from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    and_,
    not_,
    or_,
    select,
)
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.schema import Column, Table

from bi_system.modeling.contracts import (
    AggregateFunction,
    QueryRequest,
    QuerySelection,
    QuerySort,
    SortDirection,
)
from bi_system.modeling.dialect import compile_aggregate, ensure_supported_query_dialect
from bi_system.modeling.expression import (
    ComparisonOperator,
    ComparisonPredicate,
    FilterExpression,
    LogicalOperator,
    LogicalPredicate,
    NullPredicate,
    SetOperator,
    SetPredicate,
    TextOperator,
    TextPredicate,
    predicate_count,
)


class QueryCompilationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class QueryComplexityLimits:
    max_selections: int = 100
    max_group_fields: int = 20
    max_sorts: int = 10
    max_filter_predicates: int = 50
    max_result_rows: int = 10_000


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    source_id: UUID
    table: Table
    fields: Mapping[UUID, Column[Any]]


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    statement: Select[Any]
    output_names: tuple[str, ...]


class QueryCompiler:
    def __init__(
        self,
        *,
        dialect_name: str,
        limits: QueryComplexityLimits | None = None,
    ) -> None:
        ensure_supported_query_dialect(dialect_name)
        self._limits = limits or QueryComplexityLimits()

    def compile(
        self,
        request: QueryRequest,
        source: ResolvedSource,
        *,
        policy_predicates: Sequence[ColumnElement[bool]] = (),
    ) -> CompiledQuery:
        self._validate_request(request, source)
        active_column = source.table.c.get("_active")
        if active_column is None:
            raise QueryCompilationError(
                "source_missing_active_marker",
                "Resolved source does not expose the required _active column",
            )

        selected_expressions = [
            self._selection_expression(selection, source).label(selection.output_name)
            for selection in request.selections
        ]
        conditions: list[ColumnElement[bool]] = [active_column.is_(True)]
        conditions.extend(policy_predicates)
        if request.filter is not None:
            conditions.append(self._filter_expression(request.filter, source))

        statement = select(*selected_expressions).select_from(source.table).where(and_(*conditions))
        if request.group_by:
            statement = statement.group_by(
                *[self._required_field(field_id, source) for field_id in request.group_by],
            )
        if request.order_by:
            statement = statement.order_by(
                *[self._sort_expression(sort, source) for sort in request.order_by],
            )
        statement = statement.limit(request.limit)
        return CompiledQuery(
            statement=statement,
            output_names=tuple(selection.output_name for selection in request.selections),
        )

    def compile_filter(
        self,
        expression: FilterExpression,
        source: ResolvedSource,
    ) -> ColumnElement[bool]:
        predicates = (
            expression.predicates if isinstance(expression, LogicalPredicate) else (expression,)
        )
        for predicate in predicates:
            self._required_field(predicate.field_id, source)
            if isinstance(predicate, TextPredicate):
                column = self._required_field(predicate.field_id, source)
                if not isinstance(column.type, (String, Text)):
                    raise QueryCompilationError(
                        "invalid_text_filter_type",
                        "Text filters require a string field",
                    )
        return self._filter_expression(expression, source)

    def _validate_request(self, request: QueryRequest, source: ResolvedSource) -> None:
        if request.source_id != source.source_id:
            raise QueryCompilationError(
                "source_not_resolved",
                "Query source does not match the resolved source",
            )
        checks = (
            (len(request.selections), self._limits.max_selections, "too_many_selections"),
            (len(request.group_by), self._limits.max_group_fields, "too_many_group_fields"),
            (len(request.order_by), self._limits.max_sorts, "too_many_sorts"),
            (
                predicate_count(request.filter),
                self._limits.max_filter_predicates,
                "too_many_filter_predicates",
            ),
            (request.limit, self._limits.max_result_rows, "result_limit_exceeded"),
        )
        for actual, maximum, code in checks:
            if actual > maximum:
                raise QueryCompilationError(code, f"Query complexity exceeds the {maximum} limit")

        for field_id in self._referenced_field_ids(request):
            self._required_field(field_id, source)

        for selection in request.selections:
            aggregate = selection.aggregate
            if aggregate is not None and aggregate in {
                AggregateFunction.SUM,
                AggregateFunction.AVERAGE,
            }:
                column = self._required_field(selection.field_id, source)
                if not isinstance(column.type, (Integer, Numeric, Float)):
                    raise QueryCompilationError(
                        "invalid_aggregate_type",
                        f"Aggregate {aggregate.value} requires a numeric field",
                    )

        filter_expression = request.filter
        predicates = (
            filter_expression.predicates
            if isinstance(filter_expression, LogicalPredicate)
            else (() if filter_expression is None else (filter_expression,))
        )
        for predicate in predicates:
            if isinstance(predicate, TextPredicate):
                column = self._required_field(predicate.field_id, source)
                if not isinstance(column.type, (String, Text)):
                    raise QueryCompilationError(
                        "invalid_text_filter_type",
                        "Text filters require a string field",
                    )

    def _referenced_field_ids(self, request: QueryRequest) -> set[UUID]:
        field_ids = {selection.field_id for selection in request.selections}
        field_ids.update(request.group_by)
        field_ids.update(sort.field_id for sort in request.order_by)
        if request.filter is not None:
            if isinstance(request.filter, LogicalPredicate):
                field_ids.update(predicate.field_id for predicate in request.filter.predicates)
            else:
                field_ids.add(request.filter.field_id)
        return field_ids

    def _selection_expression(
        self,
        selection: QuerySelection,
        source: ResolvedSource,
    ) -> ColumnElement[Any]:
        column = self._required_field(selection.field_id, source)
        if selection.aggregate is None:
            return column
        return compile_aggregate(selection.aggregate, column)

    def _sort_expression(
        self,
        sort: QuerySort,
        source: ResolvedSource,
    ) -> ColumnElement[Any]:
        column: ColumnElement[Any] = self._required_field(sort.field_id, source)
        if sort.aggregate is not None:
            column = compile_aggregate(sort.aggregate, column)
        if sort.direction is SortDirection.DESCENDING:
            return column.desc()
        return column.asc()

    def _filter_expression(
        self,
        expression: FilterExpression,
        source: ResolvedSource,
    ) -> ColumnElement[bool]:
        if isinstance(expression, LogicalPredicate):
            predicates = [
                self._atomic_filter_expression(predicate, source)
                for predicate in expression.predicates
            ]
            if expression.operator is LogicalOperator.OR:
                return or_(*predicates)
            return and_(*predicates)
        return self._atomic_filter_expression(expression, source)

    def _atomic_filter_expression(
        self,
        expression: ComparisonPredicate | NullPredicate | SetPredicate | TextPredicate,
        source: ResolvedSource,
    ) -> ColumnElement[bool]:
        column = self._required_field(expression.field_id, source)
        if isinstance(expression, ComparisonPredicate):
            value = self._bind_value(column, expression.value)
            comparisons = {
                ComparisonOperator.EQUAL: column == value,
                ComparisonOperator.NOT_EQUAL: column != value,
                ComparisonOperator.GREATER_THAN: column > value,
                ComparisonOperator.GREATER_THAN_OR_EQUAL: column >= value,
                ComparisonOperator.LESS_THAN: column < value,
                ComparisonOperator.LESS_THAN_OR_EQUAL: column <= value,
            }
            return comparisons[expression.operator]
        if isinstance(expression, NullPredicate):
            predicate = column.is_(None)
            return predicate if expression.is_null else column.is_not(None)
        if isinstance(expression, SetPredicate):
            values = [self._bind_value(column, value) for value in expression.values]
            predicate = column.in_(values)
            return not_(predicate) if expression.operator is SetOperator.NOT_IN else predicate

        escaped = _escape_like(expression.value)
        patterns = {
            TextOperator.CONTAINS: f"%{escaped}%",
            TextOperator.STARTS_WITH: f"{escaped}%",
            TextOperator.ENDS_WITH: f"%{escaped}",
        }
        return column.like(patterns[expression.operator], escape="\\")

    @staticmethod
    def _bind_value(column: Column[Any], value: object) -> object:
        column_type = column.type
        valid = False
        normalized = value
        if isinstance(column_type, (String, Text)):
            valid = isinstance(value, str)
        elif isinstance(column_type, Boolean):
            valid = type(value) is bool
        elif isinstance(column_type, Integer):
            valid = type(value) is int
        elif isinstance(column_type, Numeric):
            if isinstance(value, str):
                try:
                    normalized = Decimal(value)
                except InvalidOperation:
                    valid = False
                else:
                    valid = normalized.is_finite()
            elif type(value) in {int, float, Decimal}:
                valid = not isinstance(value, float) or isfinite(value)
                valid = valid and (not isinstance(value, Decimal) or value.is_finite())
        elif isinstance(column_type, Float):
            valid = type(value) in {int, float, Decimal}
            valid = valid and (not isinstance(value, float) or isfinite(value))
            valid = valid and (not isinstance(value, Decimal) or value.is_finite())
        elif isinstance(column_type, DateTime):
            if isinstance(value, str):
                try:
                    normalized = datetime.fromisoformat(value)
                except ValueError:
                    valid = False
                else:
                    valid = True
            else:
                valid = isinstance(value, datetime)
        elif isinstance(column_type, Date):
            if isinstance(value, str):
                try:
                    normalized = date.fromisoformat(value)
                except ValueError:
                    valid = False
                else:
                    valid = True
            else:
                valid = type(value) is date
        if not valid:
            raise QueryCompilationError(
                "invalid_filter_value",
                "Filter value is incompatible with the resolved field",
            )
        return normalized

    @staticmethod
    def _required_field(field_id: UUID, source: ResolvedSource) -> Column[Any]:
        column = source.fields.get(field_id)
        if column is None:
            raise QueryCompilationError(
                "field_not_resolved",
                f"Field {field_id} is not available in the resolved source",
            )
        if column.table is not source.table:
            raise QueryCompilationError(
                "field_source_mismatch",
                "Resolved field does not belong to the resolved source table",
            )
        return column


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
