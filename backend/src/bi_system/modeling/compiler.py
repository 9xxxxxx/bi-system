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
    case,
    cast,
    literal,
    not_,
    or_,
    select,
)
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.schema import Column, Table
from sqlalchemy.sql.selectable import FromClause

from bi_system.modeling.calculated_field_contracts import (
    CalculatedBinary,
    CalculatedExpression,
    CalculatedFieldReference,
    CalculatedLiteral,
    CalculatedSafeDivide,
)
from bi_system.modeling.contracts import (
    AggregateFunction,
    DatasetQueryRequest,
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
from bi_system.modeling.metric_contracts import (
    MetricAggregate,
    MetricBinary,
    MetricExpression,
    MetricLiteral,
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
    fields: Mapping[UUID, ColumnElement[Any]]
    from_clause: FromClause | None = None
    tables: tuple[FromClause, ...] = ()
    mandatory_predicates: tuple[ColumnElement[bool], ...] = ()
    batch_columns: tuple[Column[Any], ...] = ()
    calculated_field_ids: frozenset[UUID] = frozenset()

    @property
    def selectable(self) -> FromClause:
        return self.from_clause if self.from_clause is not None else self.table

    @property
    def allowed_tables(self) -> tuple[FromClause, ...]:
        return self.tables if self.tables else (self.table,)


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    statement: Select[Any]
    output_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedMetricSelection:
    metric_version_id: UUID
    output_name: str
    formula: MetricExpression


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
        mandatory_predicates = self._mandatory_predicates(source)
        if not mandatory_predicates:
            raise QueryCompilationError(
                "source_missing_active_marker",
                "Resolved source does not expose the required _active column",
            )

        selected_expressions = [
            self._selection_expression(selection, source).label(selection.output_name)
            for selection in request.selections
        ]
        conditions: list[ColumnElement[bool]] = list(mandatory_predicates)
        conditions.extend(policy_predicates)
        if request.filter is not None:
            conditions.append(self._filter_expression(request.filter, source))

        statement = (
            select(*selected_expressions).select_from(source.selectable).where(and_(*conditions))
        )
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

    def compile_dataset_query(
        self,
        request: DatasetQueryRequest,
        source: ResolvedSource,
        *,
        metrics: Sequence[ResolvedMetricSelection],
        policy_predicates: Sequence[ColumnElement[bool]] = (),
    ) -> CompiledQuery:
        if not request.metrics:
            return self.compile(
                request.for_source(source.source_id),
                source,
                policy_predicates=policy_predicates,
            )
        expected_metrics = [
            (selection.metric_id, selection.output_name) for selection in request.metrics
        ]
        resolved_metrics = [
            (selection.metric_version_id, selection.output_name) for selection in metrics
        ]
        if expected_metrics != resolved_metrics:
            raise QueryCompilationError(
                "metric_not_resolved",
                "Resolved metrics do not match the dataset query",
            )
        self._validate_dataset_metric_request(request, source, metrics)
        mandatory_predicates = self._mandatory_predicates(source)
        if not mandatory_predicates:
            raise QueryCompilationError(
                "source_missing_active_marker",
                "Resolved source does not expose the required _active column",
            )

        selected_expressions = [
            self._selection_expression(selection, source).label(selection.output_name)
            for selection in request.selections
        ]
        selected_expressions.extend(
            self._metric_expression(metric.formula, source).label(metric.output_name)
            for metric in metrics
        )
        conditions: list[ColumnElement[bool]] = list(mandatory_predicates)
        conditions.extend(policy_predicates)
        if request.filter is not None:
            conditions.append(self._filter_expression(request.filter, source))

        statement = (
            select(*selected_expressions).select_from(source.selectable).where(and_(*conditions))
        )
        if request.group_by:
            statement = statement.group_by(
                *[self._required_field(field_id, source) for field_id in request.group_by]
            )
        if request.order_by:
            statement = statement.order_by(
                *[self._sort_expression(sort, source) for sort in request.order_by]
            )
        statement = statement.limit(request.limit)
        return CompiledQuery(
            statement=statement,
            output_names=tuple(
                [selection.output_name for selection in request.selections]
                + [metric.output_name for metric in metrics]
            ),
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

    def compile_calculated_expression(
        self,
        expression: CalculatedExpression,
        source: ResolvedSource,
        *,
        data_type: str,
    ) -> ColumnElement[Any]:
        compiled = self._calculated_expression(
            expression,
            source,
            expected_data_type=data_type,
        )
        sql_type = {
            "string": String(),
            "integer": Integer(),
            "decimal": Numeric(38, 10),
            "boolean": Boolean(),
            "date": Date(),
            "datetime": DateTime(),
        }.get(data_type)
        if sql_type is None:
            raise QueryCompilationError(
                "calculated_field_type_invalid",
                "Calculated field has an unsupported data type",
            )
        return cast(compiled, sql_type)

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

    def _validate_dataset_metric_request(
        self,
        request: DatasetQueryRequest,
        source: ResolvedSource,
        metrics: Sequence[ResolvedMetricSelection],
    ) -> None:
        checks = (
            (
                len(request.selections) + len(request.metrics),
                self._limits.max_selections,
                "too_many_selections",
            ),
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

        for field_id in self._referenced_dataset_field_ids(request):
            self._required_field(field_id, source)
        for selection in request.selections:
            self._validate_aggregate_field(selection.aggregate, selection.field_id, source)
        for metric in metrics:
            self._validate_metric_expression(metric.formula, source)

        expression = request.filter
        predicates = (
            expression.predicates
            if isinstance(expression, LogicalPredicate)
            else (() if expression is None else (expression,))
        )
        for predicate in predicates:
            if isinstance(predicate, TextPredicate):
                column = self._required_field(predicate.field_id, source)
                if not isinstance(column.type, (String, Text)):
                    raise QueryCompilationError(
                        "invalid_text_filter_type",
                        "Text filters require a string field",
                    )

    def _validate_aggregate_field(
        self,
        aggregate: AggregateFunction | None,
        field_id: UUID,
        source: ResolvedSource,
    ) -> None:
        if aggregate is None:
            return
        if aggregate in {
            AggregateFunction.SUM,
            AggregateFunction.AVERAGE,
            AggregateFunction.MINIMUM,
            AggregateFunction.MAXIMUM,
        }:
            column = self._required_field(field_id, source)
            if not isinstance(column.type, (Integer, Numeric, Float)):
                raise QueryCompilationError(
                    "invalid_aggregate_type",
                    f"Aggregate {aggregate.value} requires a numeric field",
                )

    def _validate_metric_expression(
        self,
        expression: MetricExpression,
        source: ResolvedSource,
    ) -> None:
        if isinstance(expression, MetricAggregate):
            self._validate_aggregate_field(expression.function, expression.field_id, source)
            return
        if isinstance(expression, MetricLiteral):
            return
        children = (
            (expression.left, expression.right)
            if isinstance(expression, MetricBinary)
            else (expression.numerator, expression.denominator)
        )
        for child in children:
            self._validate_metric_expression(child, source)

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

    def _referenced_dataset_field_ids(self, request: DatasetQueryRequest) -> set[UUID]:
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

    def _metric_expression(
        self,
        expression: MetricExpression,
        source: ResolvedSource,
    ) -> ColumnElement[Any]:
        if isinstance(expression, MetricAggregate):
            column = self._required_field(expression.field_id, source)
            return compile_aggregate(expression.function, column)
        if isinstance(expression, MetricLiteral):
            return literal(expression.value)
        if isinstance(expression, MetricBinary):
            left = self._metric_expression(expression.left, source)
            right = self._metric_expression(expression.right, source)
            if expression.op == "add":
                return left + right
            if expression.op == "subtract":
                return left - right
            return left * right

        numerator = self._metric_expression(expression.numerator, source)
        denominator = self._metric_expression(expression.denominator, source)
        fallback = literal(expression.fallback)
        return case(
            (or_(denominator == 0, denominator.is_(None)), fallback),
            else_=numerator / denominator,
        )

    def _calculated_expression(
        self,
        expression: CalculatedExpression,
        source: ResolvedSource,
        *,
        expected_data_type: str | None = None,
    ) -> ColumnElement[Any]:
        if isinstance(expression, CalculatedFieldReference):
            return self._required_field(expression.field_id, source)
        if isinstance(expression, CalculatedLiteral):
            value = expression.value
            if isinstance(value, str) and expected_data_type == "date":
                value = date.fromisoformat(value)
            elif isinstance(value, str) and expected_data_type == "datetime":
                value = datetime.fromisoformat(value)
            return literal(value)
        if isinstance(expression, CalculatedBinary):
            left = self._calculated_expression(expression.left, source)
            right = self._calculated_expression(expression.right, source)
            if expression.op == "add":
                return left + right
            if expression.op == "subtract":
                return left - right
            return left * right
        if isinstance(expression, CalculatedSafeDivide):
            numerator = self._calculated_expression(expression.numerator, source)
            denominator = self._calculated_expression(expression.denominator, source)
            return case(
                (
                    or_(denominator == 0, denominator.is_(None)),
                    literal(expression.fallback),
                ),
                else_=numerator / denominator,
            )
        condition = self.compile_filter(expression.when, source)
        then_expression = self._calculated_expression(
            expression.then,
            source,
            expected_data_type=expected_data_type,
        )
        else_expression = self._calculated_expression(
            expression.else_,
            source,
            expected_data_type=expected_data_type,
        )
        return case((condition, then_expression), else_=else_expression)

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
    def _bind_value(column: ColumnElement[Any], value: object) -> object:
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
    def _required_field(field_id: UUID, source: ResolvedSource) -> ColumnElement[Any]:
        column = source.fields.get(field_id)
        if column is None:
            raise QueryCompilationError(
                "field_not_resolved",
                f"Field {field_id} is not available in the resolved source",
            )
        if field_id in source.calculated_field_ids:
            return column
        column_table = getattr(column, "table", None)
        if not any(column_table is table for table in source.allowed_tables):
            raise QueryCompilationError(
                "field_source_mismatch",
                "Resolved field does not belong to the resolved source table",
            )
        return column

    @staticmethod
    def _mandatory_predicates(source: ResolvedSource) -> tuple[ColumnElement[bool], ...]:
        if source.mandatory_predicates:
            return source.mandatory_predicates
        active_column = source.table.c.get("_active")
        return () if active_column is None else (active_column.is_(True),)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
