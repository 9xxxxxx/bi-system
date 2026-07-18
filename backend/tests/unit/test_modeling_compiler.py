from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from bi_system.db.session import create_database_engine
from bi_system.modeling.compiler import (
    QueryCompilationError,
    QueryCompiler,
    QueryComplexityLimits,
    ResolvedMetricSelection,
    ResolvedSource,
)
from bi_system.modeling.contracts import DatasetQueryRequest, QueryRequest
from bi_system.modeling.dialect import UnsupportedQueryDialectError
from bi_system.modeling.expression import ComparisonOperator, ComparisonPredicate
from bi_system.modeling.metric_contracts import parse_metric_expression
from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, Numeric, String, Table


@pytest.fixture
def source() -> tuple[ResolvedSource, dict[str, UUID]]:
    ids = {
        "city": uuid4(),
        "amount": uuid4(),
        "department": uuid4(),
        "sold_at": uuid4(),
    }
    table = Table(
        f"data_{uuid4().hex}",
        MetaData(),
        Column("_active", Boolean, nullable=False),
        Column("city", String),
        Column("amount", Integer),
        Column("department", String),
        Column("sold_at", DateTime(timezone=True)),
    )
    return (
        ResolvedSource(
            source_id=uuid4(),
            table=table,
            fields={
                ids["city"]: table.c.city,
                ids["amount"]: table.c.amount,
                ids["department"]: table.c.department,
                ids["sold_at"]: table.c.sold_at,
            },
        ),
        ids,
    )


def test_compiler_injects_active_filter_and_binds_untrusted_values(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    injection = "北京' OR 1=1 --"
    request = QueryRequest.model_validate(
        {
            "source_id": str(resolved.source_id),
            "selections": [{"field_id": str(ids["city"]), "output_name": "city"}],
            "filter": {
                "kind": "comparison",
                "field_id": str(ids["city"]),
                "operator": "eq",
                "value": injection,
            },
            "limit": 25,
        },
    )

    compiled = QueryCompiler(dialect_name="sqlite").compile(request, resolved)
    sql = str(compiled.statement.compile())
    parameters = compiled.statement.compile().params

    assert "_active" in sql
    assert injection not in sql
    assert injection in parameters.values()
    assert compiled.output_names == ("city",)


def test_compiler_executes_grouped_aggregate_and_policy_predicate(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    resolved.table.create(engine)
    with engine.begin() as connection:
        connection.execute(
            resolved.table.insert(),
            [
                {"_active": True, "city": "北京", "amount": 10, "department": "销售"},
                {"_active": True, "city": "北京", "amount": 20, "department": "研发"},
                {"_active": False, "city": "北京", "amount": 999, "department": "销售"},
                {"_active": True, "city": "上海", "amount": 30, "department": "销售"},
            ],
        )
        request = QueryRequest.model_validate(
            {
                "source_id": str(resolved.source_id),
                "selections": [
                    {"field_id": str(ids["city"]), "output_name": "city"},
                    {
                        "field_id": str(ids["amount"]),
                        "output_name": "total_amount",
                        "aggregate": "sum",
                    },
                ],
                "group_by": [str(ids["city"])],
                "order_by": [{"field_id": str(ids["city"]), "direction": "asc"}],
            },
        )
        compiled = QueryCompiler(dialect_name="sqlite").compile(
            request,
            resolved,
            policy_predicates=(resolved.table.c.department == "销售",),
        )
        rows = connection.execute(compiled.statement).mappings().all()

    engine.dispose()
    assert rows == [
        {"city": "上海", "total_amount": 30},
        {"city": "北京", "total_amount": 10},
    ]


def test_compiler_executes_bound_metric_formula_after_governance_filters(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    resolved.table.create(engine)
    metric_id = uuid4()
    formula = parse_metric_expression(
        {
            "op": "safe_divide",
            "numerator": {
                "op": "multiply",
                "left": {
                    "op": "subtract",
                    "left": {
                        "op": "add",
                        "left": {
                            "op": "aggregate",
                            "function": "sum",
                            "field_id": ids["amount"],
                        },
                        "right": {"op": "literal", "value": 10},
                    },
                    "right": {"op": "literal", "value": 5},
                },
                "right": {"op": "literal", "value": 2},
            },
            "denominator": {
                "op": "aggregate",
                "function": "count",
                "field_id": ids["amount"],
            },
            "fallback": 0,
        }
    )
    request = DatasetQueryRequest.model_validate(
        {
            "dataset_id": uuid4(),
            "selections": [{"field_id": ids["city"], "output_name": "city"}],
            "metrics": [{"metric_id": metric_id, "output_name": "adjusted_average"}],
            "group_by": [ids["city"]],
            "order_by": [{"field_id": ids["city"], "direction": "asc"}],
        }
    )
    with engine.begin() as connection:
        connection.execute(
            resolved.table.insert(),
            [
                {"_active": True, "city": "北京", "amount": 10, "department": "销售"},
                {"_active": True, "city": "北京", "amount": 20, "department": "研发"},
                {"_active": False, "city": "北京", "amount": 999, "department": "销售"},
                {"_active": True, "city": "上海", "amount": 30, "department": "销售"},
            ],
        )
        compiled = QueryCompiler(dialect_name="sqlite").compile_dataset_query(
            request,
            resolved,
            metrics=(
                ResolvedMetricSelection(
                    metric_version_id=metric_id,
                    output_name="adjusted_average",
                    formula=formula,
                ),
            ),
            policy_predicates=(resolved.table.c.department == "销售",),
        )
        statement = compiled.statement
        rows = connection.execute(statement).mappings().all()
        parameters = statement.compile().params.values()

    engine.dispose()
    assert rows == [
        {"city": "上海", "adjusted_average": 70},
        {"city": "北京", "adjusted_average": 30},
    ]
    assert {str(value) for value in parameters}.issuperset({"10", "5", "2", "0"})


def test_compiler_executes_portable_time_grain_and_metric_sort(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    resolved.table.create(engine)
    metric_id = uuid4()
    formula = parse_metric_expression(
        {
            "op": "aggregate",
            "function": "sum",
            "field_id": ids["amount"],
        }
    )
    request = DatasetQueryRequest.model_validate(
        {
            "dataset_id": uuid4(),
            "selections": [
                {
                    "field_id": ids["sold_at"],
                    "output_name": "month",
                    "time_grain": "month",
                }
            ],
            "metrics": [{"metric_id": metric_id, "output_name": "revenue"}],
            "group_by": [ids["sold_at"]],
            "order_by": [
                {
                    "kind": "metric",
                    "metric_id": metric_id,
                    "direction": "desc",
                }
            ],
        }
    )
    with engine.begin() as connection:
        connection.execute(
            resolved.table.insert(),
            [
                {
                    "_active": True,
                    "city": "上海",
                    "amount": 10,
                    "department": "销售",
                    "sold_at": datetime(2026, 1, 2, tzinfo=UTC),
                },
                {
                    "_active": True,
                    "city": "北京",
                    "amount": 20,
                    "department": "销售",
                    "sold_at": datetime(2026, 1, 18, tzinfo=UTC),
                },
                {
                    "_active": True,
                    "city": "深圳",
                    "amount": 40,
                    "department": "销售",
                    "sold_at": datetime(2026, 2, 1, tzinfo=UTC),
                },
            ],
        )
        compiled = QueryCompiler(dialect_name="sqlite").compile_dataset_query(
            request,
            resolved,
            metrics=(
                ResolvedMetricSelection(
                    metric_version_id=metric_id,
                    output_name="revenue",
                    formula=formula,
                ),
            ),
        )
        rows = connection.execute(compiled.statement).mappings().all()

    engine.dispose()
    assert rows == [
        {"month": "2026-02-01", "revenue": 40},
        {"month": "2026-01-01", "revenue": 30},
    ]


def test_compiler_sorts_nulls_last_portably(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    resolved.table.create(engine)
    request = QueryRequest.model_validate(
        {
            "source_id": resolved.source_id,
            "selections": [
                {"field_id": ids["city"], "output_name": "city"},
                {"field_id": ids["amount"], "output_name": "amount"},
            ],
            "order_by": [
                {"field_id": ids["amount"], "direction": "desc"},
            ],
        }
    )
    with engine.begin() as connection:
        connection.execute(
            resolved.table.insert(),
            [
                {"_active": True, "city": "空值", "amount": None},
                {"_active": True, "city": "低", "amount": 1},
                {"_active": True, "city": "高", "amount": 2},
            ],
        )
        rows = (
            connection.execute(
                QueryCompiler(dialect_name="sqlite").compile(request, resolved).statement
            )
            .mappings()
            .all()
        )

    engine.dispose()
    assert [row["city"] for row in rows] == ["高", "低", "空值"]


def test_compiler_enforces_shared_scoped_filter_budget(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    request = QueryRequest.model_validate(
        {
            "source_id": resolved.source_id,
            "selections": [{"field_id": ids["city"], "output_name": "city"}],
        }
    )
    filters = tuple(
        ComparisonPredicate(
            kind="comparison",
            field_id=ids["amount"],
            operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
            value=index,
        )
        for index in range(51)
    )

    with pytest.raises(QueryCompilationError) as error:
        QueryCompiler(dialect_name="sqlite").compile(
            request,
            resolved,
            scoped_filters=filters,
        )

    assert error.value.code == "too_many_filter_predicates"


def test_compiler_rejects_unknown_fields_and_non_numeric_sum(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    unknown_request = QueryRequest.model_validate(
        {
            "source_id": str(resolved.source_id),
            "selections": [{"field_id": str(uuid4()), "output_name": "unknown"}],
        },
    )
    with pytest.raises(QueryCompilationError) as unknown_error:
        QueryCompiler(dialect_name="sqlite").compile(unknown_request, resolved)
    assert unknown_error.value.code == "field_not_resolved"

    invalid_sum = QueryRequest.model_validate(
        {
            "source_id": str(resolved.source_id),
            "selections": [
                {
                    "field_id": str(ids["city"]),
                    "output_name": "total_city",
                    "aggregate": "sum",
                },
            ],
        },
    )
    with pytest.raises(QueryCompilationError) as aggregate_error:
        QueryCompiler(dialect_name="sqlite").compile(invalid_sum, resolved)
    assert aggregate_error.value.code == "invalid_aggregate_type"


def test_compiler_rejects_text_filter_on_numeric_field(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    request = QueryRequest.model_validate(
        {
            "source_id": str(resolved.source_id),
            "selections": [{"field_id": str(ids["amount"]), "output_name": "amount"}],
            "filter": {
                "kind": "text",
                "field_id": str(ids["amount"]),
                "operator": "contains",
                "value": "1",
            },
        },
    )

    with pytest.raises(QueryCompilationError) as error:
        QueryCompiler(dialect_name="sqlite").compile(request, resolved)
    assert error.value.code == "invalid_text_filter_type"


def test_compiler_validates_filter_value_against_resolved_column_type(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    request = QueryRequest.model_validate(
        {
            "source_id": str(resolved.source_id),
            "selections": [{"field_id": str(ids["amount"]), "output_name": "amount"}],
            "filter": {
                "kind": "comparison",
                "field_id": str(ids["amount"]),
                "operator": "eq",
                "value": "not-a-number",
            },
        },
    )

    with pytest.raises(QueryCompilationError) as error:
        QueryCompiler(dialect_name="postgresql").compile(request, resolved)
    assert error.value.code == "invalid_filter_value"


def test_decimal_filter_string_is_normalized_to_decimal() -> None:
    field_id = uuid4()
    table = Table(
        f"data_{uuid4().hex}",
        MetaData(),
        Column("_active", Boolean, nullable=False),
        Column("amount", Numeric(38, 10)),
    )
    source = ResolvedSource(source_id=uuid4(), table=table, fields={field_id: table.c.amount})
    request = QueryRequest.model_validate(
        {
            "source_id": str(source.source_id),
            "selections": [{"field_id": str(field_id), "output_name": "amount"}],
            "filter": {
                "kind": "comparison",
                "field_id": str(field_id),
                "operator": "eq",
                "value": "12.345",
            },
        },
    )

    compiled = QueryCompiler(dialect_name="sqlite").compile(request, source)

    assert str(next(value for value in compiled.statement.compile().params.values())) == "12.345"


def test_compiler_enforces_runtime_complexity_limits(
    source: tuple[ResolvedSource, dict[str, UUID]],
) -> None:
    resolved, ids = source
    request = QueryRequest.model_validate(
        {
            "source_id": str(resolved.source_id),
            "selections": [
                {"field_id": str(ids["city"]), "output_name": "city"},
                {"field_id": str(ids["amount"]), "output_name": "amount"},
            ],
            "limit": 2,
        },
    )
    compiler = QueryCompiler(
        dialect_name="sqlite",
        limits=QueryComplexityLimits(max_selections=1, max_result_rows=1),
    )

    with pytest.raises(QueryCompilationError) as error:
        compiler.compile(request, resolved)
    assert error.value.code == "too_many_selections"


def test_compiler_rejects_unsupported_dialect() -> None:
    with pytest.raises(UnsupportedQueryDialectError):
        QueryCompiler(dialect_name="mysql")
