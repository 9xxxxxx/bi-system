from collections.abc import Callable
from typing import Any

from sqlalchemy import Date, Integer, cast, distinct, func
from sqlalchemy.sql.elements import ColumnElement

from bi_system.modeling.contracts import AggregateFunction, SortDirection, TimeGrain


class UnsupportedQueryDialectError(ValueError):
    pass


SUPPORTED_QUERY_DIALECTS = frozenset({"sqlite", "postgresql"})


def ensure_supported_query_dialect(dialect_name: str) -> None:
    if dialect_name not in SUPPORTED_QUERY_DIALECTS:
        raise UnsupportedQueryDialectError(f"Unsupported query dialect: {dialect_name}")


def compile_aggregate(
    function: AggregateFunction,
    column: ColumnElement[Any],
) -> ColumnElement[Any]:
    aggregators: dict[AggregateFunction, Callable[[], ColumnElement[Any]]] = {
        AggregateFunction.SUM: lambda: func.sum(column),
        AggregateFunction.AVERAGE: lambda: func.avg(column),
        AggregateFunction.COUNT: lambda: func.count(column),
        AggregateFunction.COUNT_DISTINCT: lambda: func.count(distinct(column)),
        AggregateFunction.MINIMUM: lambda: func.min(column),
        AggregateFunction.MAXIMUM: lambda: func.max(column),
    }
    return aggregators[function]()


def compile_time_grain(
    grain: TimeGrain,
    column: ColumnElement[Any],
    *,
    dialect_name: str,
) -> ColumnElement[Any]:
    ensure_supported_query_dialect(dialect_name)
    if dialect_name == "postgresql":
        return cast(func.date_trunc(grain.value, column), Date)

    if grain is TimeGrain.DAY:
        return func.date(column)
    if grain is TimeGrain.WEEK:
        return func.date(column, "-6 days", "weekday 1")
    if grain is TimeGrain.MONTH:
        return func.strftime("%Y-%m-01", column)
    if grain is TimeGrain.QUARTER:
        year = cast(func.strftime("%Y", column), Integer)
        month = cast(func.strftime("%m", column), Integer)
        quarter_month = cast((month - 1) / 3, Integer) * 3 + 1
        return func.printf("%04d-%02d-01", year, quarter_month)
    return func.strftime("%Y-01-01", column)


def compile_sort_terms(
    expression: ColumnElement[Any],
    direction: SortDirection,
) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    value_term = expression.desc() if direction is SortDirection.DESCENDING else expression.asc()
    return expression.is_(None).asc(), value_term
