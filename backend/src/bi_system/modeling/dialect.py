from collections.abc import Callable
from typing import Any

from sqlalchemy import distinct, func
from sqlalchemy.sql.elements import ColumnElement

from bi_system.modeling.contracts import AggregateFunction


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
