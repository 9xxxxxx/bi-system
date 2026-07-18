from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from bi_system.dashboards.filters import (
    AbsoluteDateRangeFilter,
    DashboardFilterError,
    RelativeDateFilter,
    RelativeDatePeriod,
    resolve_scoped_filters,
)
from bi_system.modeling.expression import (
    ComparisonOperator,
    ComparisonPredicate,
    LogicalOperator,
    LogicalPredicate,
    SetOperator,
    SetPredicate,
    TextOperator,
    TextPredicate,
    predicate_count,
)


def _comparison(field_id: UUID, value: str) -> ComparisonPredicate:
    return ComparisonPredicate(
        kind="comparison",
        field_id=field_id,
        operator=ComparisonOperator.EQUAL,
        value=value,
    )


def test_scoped_filters_preserve_global_page_component_order_without_flattening() -> None:
    global_field = uuid4()
    page_field = uuid4()
    component_field = uuid4()
    global_filter = _comparison(global_field, "2026")
    page_filter = SetPredicate(
        kind="set",
        field_id=page_field,
        operator=SetOperator.IN,
        values=["north", "south"],
    )
    component_filter = TextPredicate(
        kind="text",
        field_id=component_field,
        operator=TextOperator.CONTAINS,
        value="hardware",
    )

    resolved = resolve_scoped_filters(
        global_filter,
        page_filter,
        component_filter,
        "Asia/Hong_Kong",
    )

    assert resolved.filters == (global_filter, page_filter, component_filter)
    assert resolved.evidence == ()
    assert [predicate_count(item) for item in resolved.filters] == [1, 1, 1]


def test_empty_scopes_are_omitted() -> None:
    component_filter = _comparison(uuid4(), "hardware")

    resolved = resolve_scoped_filters(
        None,
        None,
        component_filter,
        "UTC",
    )

    assert resolved.filters == (component_filter,)


@pytest.mark.parametrize(
    ("period", "expected_start", "expected_end"),
    [
        ("today", date(2026, 3, 18), date(2026, 3, 19)),
        ("yesterday", date(2026, 3, 17), date(2026, 3, 18)),
        ("last_7_days", date(2026, 3, 12), date(2026, 3, 19)),
        ("last_30_days", date(2026, 2, 17), date(2026, 3, 19)),
        ("this_week", date(2026, 3, 16), date(2026, 3, 23)),
        ("last_week", date(2026, 3, 9), date(2026, 3, 16)),
        ("this_month", date(2026, 3, 1), date(2026, 4, 1)),
        ("last_month", date(2026, 2, 1), date(2026, 3, 1)),
        ("month_to_date", date(2026, 3, 1), date(2026, 3, 19)),
        ("year_to_date", date(2026, 1, 1), date(2026, 3, 19)),
    ],
)
def test_relative_date_periods_resolve_to_closed_open_calendar_boundaries(
    period: RelativeDatePeriod,
    expected_start: date,
    expected_end: date,
) -> None:
    field_id = uuid4()
    resolved = resolve_scoped_filters(
        RelativeDateFilter(
            field_id=field_id,
            field_type="date",
            period=period,
        ),
        None,
        None,
        "UTC",
        now=datetime(2026, 3, 18, 15, 30, tzinfo=UTC),
    )

    expression = resolved.filters[0]
    assert isinstance(expression, LogicalPredicate)
    assert expression.operator is LogicalOperator.AND
    predicates = [
        predicate
        for predicate in expression.predicates
        if isinstance(predicate, ComparisonPredicate)
    ]
    assert len(predicates) == 2
    assert [predicate.operator for predicate in predicates] == [
        ComparisonOperator.GREATER_THAN_OR_EQUAL,
        ComparisonOperator.LESS_THAN,
    ]
    assert [predicate.value for predicate in predicates] == [
        expected_start,
        expected_end,
    ]
    assert resolved.evidence[0].semantic == period
    assert resolved.evidence[0].start == expected_start
    assert resolved.evidence[0].end == expected_end


def test_hong_kong_workspace_day_resolves_datetime_boundaries_to_utc() -> None:
    field_id = uuid4()
    resolved = resolve_scoped_filters(
        {
            "kind": "relative_date",
            "field_id": field_id,
            "data_type": "datetime",
            "value": "today",
        },
        None,
        None,
        "Asia/Hong_Kong",
        now=datetime(2026, 1, 5, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )

    evidence = resolved.evidence[0]
    assert evidence.start == datetime(2026, 1, 4, 16, tzinfo=UTC)
    assert evidence.end == datetime(2026, 1, 5, 16, tzinfo=UTC)
    assert evidence.resolved_at == datetime(2026, 1, 5, 4, tzinfo=UTC)
    assert evidence.timezone == "Asia/Hong_Kong"


def test_new_york_spring_forward_day_uses_23_hour_utc_interval() -> None:
    resolved = resolve_scoped_filters(
        RelativeDateFilter(
            field_id=uuid4(),
            field_type="datetime",
            period=RelativeDatePeriod.TODAY,
        ),
        None,
        None,
        "America/New_York",
        now=datetime(2026, 3, 8, 12, tzinfo=ZoneInfo("America/New_York")),
    )

    evidence = resolved.evidence[0]
    assert isinstance(evidence.start, datetime)
    assert isinstance(evidence.end, datetime)
    assert evidence.start == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert evidence.end == datetime(2026, 3, 9, 4, tzinfo=UTC)
    assert evidence.end - evidence.start == timedelta(hours=23)


def test_absolute_date_and_datetime_ranges_use_gte_and_lt_boundaries() -> None:
    date_field = uuid4()
    datetime_field = uuid4()
    resolved = resolve_scoped_filters(
        AbsoluteDateRangeFilter(
            field_id=date_field,
            field_type="date",
            start="2026-01-01",
            end="2026-02-01",
        ),
        None,
        AbsoluteDateRangeFilter(
            field_id=datetime_field,
            field_type="datetime",
            start="2026-01-05T00:00:00+08:00",
            end="2026-01-06T00:00:00+08:00",
        ),
        "Asia/Hong_Kong",
        now=datetime(2026, 1, 6, tzinfo=UTC),
    )

    assert [item.scope for item in resolved.evidence] == ["global", "component"]
    assert resolved.evidence[0].start == date(2026, 1, 1)
    assert resolved.evidence[0].end == date(2026, 2, 1)
    assert resolved.evidence[1].start == datetime(2026, 1, 4, 16, tzinfo=UTC)
    assert resolved.evidence[1].end == datetime(2026, 1, 5, 16, tzinfo=UTC)


def test_three_scopes_share_one_50_predicate_budget_after_date_expansion() -> None:
    regular_field = uuid4()
    date_field = uuid4()

    def logical_filter(count: int) -> dict[str, object]:
        return {
            "kind": "logical",
            "operator": "and",
            "predicates": [
                {
                    "kind": "comparison",
                    "field_id": regular_field,
                    "operator": "eq",
                    "value": index,
                }
                for index in range(count)
            ],
        }

    accepted = resolve_scoped_filters(
        logical_filter(48),
        {
            "kind": "relative_date",
            "field_id": date_field,
            "field_type": "date",
            "period": "today",
        },
        None,
        "UTC",
        now=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert sum(predicate_count(item) for item in accepted.filters) == 50

    with pytest.raises(DashboardFilterError) as captured:
        resolve_scoped_filters(
            logical_filter(49),
            {
                "kind": "relative_date",
                "field_id": date_field,
                "field_type": "date",
                "period": "today",
            },
            None,
            "UTC",
            now=datetime(2026, 1, 5, tzinfo=UTC),
        )
    assert captured.value.code == "too_many_filter_predicates"
    assert captured.value.action


UNSUPPORTED_FILTERS: list[dict[str, object]] = [
    {
        "kind": "logical",
        "operator": "or",
        "predicates": [
            {
                "kind": "comparison",
                "field_id": uuid4(),
                "operator": "eq",
                "value": 1,
            },
            {
                "kind": "comparison",
                "field_id": uuid4(),
                "operator": "eq",
                "value": 2,
            },
        ],
    },
    {
        "kind": "logical",
        "operator": "and",
        "predicates": [
            {
                "kind": "logical",
                "operator": "and",
                "predicates": [],
            },
            {
                "kind": "comparison",
                "field_id": uuid4(),
                "operator": "eq",
                "value": 2,
            },
        ],
    },
]


@pytest.mark.parametrize("filter_value", UNSUPPORTED_FILTERS)
def test_unsupported_scope_shapes_return_stable_error_code(
    filter_value: dict[str, object],
) -> None:
    with pytest.raises(DashboardFilterError) as captured:
        resolve_scoped_filters(filter_value, None, None, "UTC")

    assert captured.value.code == "filter_expression_not_supported"
    assert captured.value.action


def test_invalid_timezone_naive_now_and_reversed_range_have_stable_codes() -> None:
    relative = RelativeDateFilter(
        field_id=uuid4(),
        field_type="date",
        period=RelativeDatePeriod.TODAY,
    )
    with pytest.raises(DashboardFilterError) as timezone_error:
        resolve_scoped_filters(relative, None, None, "Hong Kong")
    assert timezone_error.value.code == "workspace_timezone_invalid"

    with pytest.raises(DashboardFilterError) as now_error:
        resolve_scoped_filters(
            relative,
            None,
            None,
            "UTC",
            now=datetime(2026, 1, 5),
        )
    assert now_error.value.code == "filter_resolution_time_invalid"

    with pytest.raises(DashboardFilterError) as range_error:
        resolve_scoped_filters(
            AbsoluteDateRangeFilter(
                field_id=uuid4(),
                field_type="date",
                start=date(2026, 2, 1),
                end=date(2026, 1, 1),
            ),
            None,
            None,
            "UTC",
        )
    assert range_error.value.code == "filter_date_range_invalid"
