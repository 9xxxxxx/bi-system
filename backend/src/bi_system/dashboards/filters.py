from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from bi_system.modeling.expression import (
    AtomicPredicate,
    ComparisonOperator,
    ComparisonPredicate,
    FilterExpression,
    LogicalOperator,
    LogicalPredicate,
    NullPredicate,
    SetPredicate,
    TextPredicate,
)

FilterScope = Literal["global", "page", "component"]
DateFieldType = Literal["date", "datetime"]


class RelativeDatePeriod(StrEnum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    THIS_WEEK = "this_week"
    LAST_WEEK = "last_week"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    MONTH_TO_DATE = "month_to_date"
    YEAR_TO_DATE = "year_to_date"


class StrictDashboardFilterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelativeDateFilter(StrictDashboardFilterModel):
    kind: Literal["relative_date"] = "relative_date"
    field_id: UUID
    field_type: DateFieldType
    period: RelativeDatePeriod


class AbsoluteDateRangeFilter(StrictDashboardFilterModel):
    kind: Literal["absolute_date_range"] = "absolute_date_range"
    field_id: UUID
    field_type: DateFieldType
    start: date | datetime | str
    end: date | datetime | str


type DateFilter = RelativeDateFilter | AbsoluteDateRangeFilter
type ScopedFilterInput = FilterExpression | DateFilter | Mapping[str, object]
type FilterSemantic = RelativeDatePeriod | Literal["absolute"]


@dataclass(frozen=True, slots=True)
class ResolvedFilterEvidence:
    scope: FilterScope
    field_id: UUID
    field_type: DateFieldType
    semantic: FilterSemantic
    timezone: str
    start: date | datetime
    end: date | datetime
    resolved_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedScopedFilters:
    filters: tuple[FilterExpression, ...]
    evidence: tuple[ResolvedFilterEvidence, ...]


class DashboardFilterError(ValueError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.action = action


@dataclass(frozen=True, slots=True)
class _ResolvedScope:
    atoms: tuple[AtomicPredicate, ...]
    evidence: tuple[ResolvedFilterEvidence, ...]


_ATOMIC_FILTER_ADAPTER = cast(
    TypeAdapter[AtomicPredicate],
    TypeAdapter(AtomicPredicate),
)
_FILTER_ACTION = "Correct the dashboard filter configuration and try again"
_MAX_USER_PREDICATES = 50


def resolve_scoped_filters(
    global_filter: ScopedFilterInput | None,
    page_filter: ScopedFilterInput | None,
    component_filter: ScopedFilterInput | None,
    workspace_timezone: str,
    now: datetime | None = None,
) -> ResolvedScopedFilters:
    zone = _workspace_zone(workspace_timezone)
    resolved_at = _resolution_time(now)
    resolved_scopes: list[_ResolvedScope] = []
    scoped_values: tuple[tuple[FilterScope, ScopedFilterInput | None], ...] = (
        ("global", global_filter),
        ("page", page_filter),
        ("component", component_filter),
    )
    for scope, value in scoped_values:
        if value is None:
            continue
        resolved_scopes.append(
            _resolve_scope(
                scope,
                value,
                zone=zone,
                timezone_name=workspace_timezone,
                resolved_at=resolved_at,
            )
        )

    predicate_total = sum(len(scope.atoms) for scope in resolved_scopes)
    if predicate_total > _MAX_USER_PREDICATES:
        raise DashboardFilterError(
            "too_many_filter_predicates",
            "Dashboard user filter scopes may contain at most 50 predicates",
            _FILTER_ACTION,
        )

    filters = tuple(_filter_expression(scope.atoms) for scope in resolved_scopes)
    evidence = tuple(item for scope in resolved_scopes for item in scope.evidence)
    return ResolvedScopedFilters(filters=filters, evidence=evidence)


def _resolve_scope(
    scope: FilterScope,
    value: ScopedFilterInput,
    *,
    zone: ZoneInfo,
    timezone_name: str,
    resolved_at: datetime,
) -> _ResolvedScope:
    inputs = _scope_atoms(value)
    atoms: list[AtomicPredicate] = []
    evidence: list[ResolvedFilterEvidence] = []
    for item in inputs:
        if isinstance(item, (RelativeDateFilter, AbsoluteDateRangeFilter)):
            date_atoms, date_evidence = _resolve_date_filter(
                scope,
                item,
                zone=zone,
                timezone_name=timezone_name,
                resolved_at=resolved_at,
            )
            atoms.extend(date_atoms)
            evidence.append(date_evidence)
        else:
            atoms.append(item)
    return _ResolvedScope(atoms=tuple(atoms), evidence=tuple(evidence))


def _scope_atoms(value: object) -> tuple[AtomicPredicate | DateFilter, ...]:
    if isinstance(value, LogicalPredicate):
        if value.operator is not LogicalOperator.AND:
            raise _unsupported_expression()
        return tuple(value.predicates)
    if isinstance(
        value,
        (
            ComparisonPredicate,
            NullPredicate,
            SetPredicate,
            TextPredicate,
            RelativeDateFilter,
            AbsoluteDateRangeFilter,
        ),
    ):
        return (value,)
    if not isinstance(value, Mapping):
        raise _invalid_expression("Dashboard filter must be a supported filter object")
    mapping_value = cast(Mapping[str, object], value)

    kind = mapping_value.get("kind")
    if kind == "logical":
        if mapping_value.get("operator") != LogicalOperator.AND.value:
            raise _unsupported_expression()
        raw_predicates_value = mapping_value.get("predicates")
        if not isinstance(raw_predicates_value, Sequence) or isinstance(
            raw_predicates_value, (str, bytes)
        ):
            raise _invalid_expression("Logical dashboard filter predicates must be a list")
        raw_predicates = cast(Sequence[object], raw_predicates_value)
        if len(raw_predicates) < 2:
            raise _unsupported_expression()
        parsed: list[AtomicPredicate | DateFilter] = []
        for predicate in raw_predicates:
            if not isinstance(predicate, Mapping):
                raise _invalid_expression("Dashboard filter predicate must be an object")
            predicate_mapping = cast(Mapping[str, object], predicate)
            if predicate_mapping.get("kind") == "logical":
                raise _unsupported_expression()
            parsed.append(_parse_atomic_input(predicate_mapping))
        return tuple(parsed)
    return (_parse_atomic_input(mapping_value),)


def _parse_atomic_input(value: Mapping[str, object]) -> AtomicPredicate | DateFilter:
    kind = value.get("kind")
    try:
        if kind in {"relative_date", "relative_date_range"}:
            return RelativeDateFilter.model_validate(_canonical_relative_date(value))
        if kind in {"absolute_date_range", "absolute_date", "date_range"}:
            return AbsoluteDateRangeFilter.model_validate(_canonical_absolute_date(value))
        return _ATOMIC_FILTER_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _invalid_expression("Dashboard filter expression is invalid") from exc


def _canonical_relative_date(value: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "kind",
        "field_id",
        "field_type",
        "data_type",
        "period",
        "value",
        "relative_period",
    }
    if set(value) - allowed:
        raise _invalid_expression("Relative date filter contains unsupported fields")
    return {
        "kind": "relative_date",
        "field_id": value.get("field_id"),
        "field_type": value.get("field_type", value.get("data_type")),
        "period": value.get("period", value.get("value", value.get("relative_period"))),
    }


def _canonical_absolute_date(value: Mapping[str, object]) -> dict[str, object]:
    allowed = {"kind", "field_id", "field_type", "data_type", "start", "end"}
    if set(value) - allowed:
        raise _invalid_expression("Absolute date filter contains unsupported fields")
    return {
        "kind": "absolute_date_range",
        "field_id": value.get("field_id"),
        "field_type": value.get("field_type", value.get("data_type")),
        "start": value.get("start"),
        "end": value.get("end"),
    }


def _resolve_date_filter(
    scope: FilterScope,
    value: DateFilter,
    *,
    zone: ZoneInfo,
    timezone_name: str,
    resolved_at: datetime,
) -> tuple[tuple[AtomicPredicate, AtomicPredicate], ResolvedFilterEvidence]:
    if isinstance(value, RelativeDateFilter):
        local_today = resolved_at.astimezone(zone).date()
        start_date, end_date = _relative_date_boundaries(value.period, local_today)
        semantic: FilterSemantic = value.period
    else:
        start_date = value.start
        end_date = value.end
        semantic = "absolute"

    if value.field_type == "date":
        start = _as_date(start_date, zone)
        end = _as_date(end_date, zone)
    else:
        start = _as_utc_datetime(start_date, zone)
        end = _as_utc_datetime(end_date, zone)
    if end <= start:
        raise DashboardFilterError(
            "filter_date_range_invalid",
            "Dashboard date filter end must be after start",
            _FILTER_ACTION,
        )

    predicates: tuple[AtomicPredicate, AtomicPredicate] = (
        ComparisonPredicate(
            kind="comparison",
            field_id=value.field_id,
            operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
            value=start,
        ),
        ComparisonPredicate(
            kind="comparison",
            field_id=value.field_id,
            operator=ComparisonOperator.LESS_THAN,
            value=end,
        ),
    )
    evidence = ResolvedFilterEvidence(
        scope=scope,
        field_id=value.field_id,
        field_type=value.field_type,
        semantic=semantic,
        timezone=timezone_name,
        start=start,
        end=end,
        resolved_at=resolved_at,
    )
    return predicates, evidence


def _relative_date_boundaries(
    period: RelativeDatePeriod,
    today: date,
) -> tuple[date, date]:
    tomorrow = today + timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    next_month = _shift_month(month_start, 1)
    if period is RelativeDatePeriod.TODAY:
        return today, tomorrow
    if period is RelativeDatePeriod.YESTERDAY:
        return today - timedelta(days=1), today
    if period is RelativeDatePeriod.LAST_7_DAYS:
        return today - timedelta(days=6), tomorrow
    if period is RelativeDatePeriod.LAST_30_DAYS:
        return today - timedelta(days=29), tomorrow
    if period is RelativeDatePeriod.THIS_WEEK:
        return week_start, week_start + timedelta(days=7)
    if period is RelativeDatePeriod.LAST_WEEK:
        return week_start - timedelta(days=7), week_start
    if period is RelativeDatePeriod.THIS_MONTH:
        return month_start, next_month
    if period is RelativeDatePeriod.LAST_MONTH:
        return _shift_month(month_start, -1), month_start
    if period is RelativeDatePeriod.MONTH_TO_DATE:
        return month_start, tomorrow
    return today.replace(month=1, day=1), tomorrow


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _as_date(value: date | datetime | str, zone: ZoneInfo) -> date:
    parsed = _parse_temporal(value)
    if isinstance(parsed, datetime):
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.astimezone(zone).date()
        return parsed.date()
    return parsed


def _as_utc_datetime(value: date | datetime | str, zone: ZoneInfo) -> datetime:
    parsed = _parse_temporal(value)
    if isinstance(parsed, datetime):
        local = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=zone)
    else:
        local = datetime.combine(parsed, time.min, tzinfo=zone)
    return local.astimezone(UTC)


def _parse_temporal(value: date | datetime | str) -> date | datetime:
    if not isinstance(value, str):
        return value
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    if "T" in normalized or " " in normalized:
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise DashboardFilterError(
                "filter_date_range_invalid",
                "Dashboard date filter contains an invalid datetime",
                _FILTER_ACTION,
            ) from exc
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise DashboardFilterError(
            "filter_date_range_invalid",
            "Dashboard date filter contains an invalid date",
            _FILTER_ACTION,
        ) from exc


def _filter_expression(atoms: tuple[AtomicPredicate, ...]) -> FilterExpression:
    if len(atoms) == 1:
        return atoms[0]
    return LogicalPredicate(
        kind="logical",
        operator=LogicalOperator.AND,
        predicates=list(atoms),
    )


def _workspace_zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DashboardFilterError(
            "workspace_timezone_invalid",
            "Workspace timezone must be a valid IANA timezone",
            "Configure a valid IANA workspace timezone and try again",
        ) from exc


def _resolution_time(value: datetime | None) -> datetime:
    resolved = datetime.now(UTC) if value is None else value
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise DashboardFilterError(
            "filter_resolution_time_invalid",
            "Dashboard filter resolution time must include a timezone",
            _FILTER_ACTION,
        )
    return resolved.astimezone(UTC)


def _unsupported_expression() -> DashboardFilterError:
    return DashboardFilterError(
        "filter_expression_not_supported",
        "Dashboard filter scopes support only one AND layer with atomic predicates",
        _FILTER_ACTION,
    )


def _invalid_expression(message: str) -> DashboardFilterError:
    return DashboardFilterError("filter_expression_invalid", message, _FILTER_ACTION)


__all__ = [
    "AbsoluteDateRangeFilter",
    "DashboardFilterError",
    "RelativeDateFilter",
    "RelativeDatePeriod",
    "ResolvedFilterEvidence",
    "ResolvedScopedFilters",
    "resolve_scoped_filters",
]
