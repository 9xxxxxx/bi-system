from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from bi_system.db.models import Dataset, DatasetField, Metric, MetricDimension, User
from bi_system.modeling.contracts import AggregateFunction
from bi_system.modeling.metric_contracts import (
    CreateMetric,
    CreateMetricVersion,
    MetricAggregate,
    MetricBinary,
    MetricExpression,
    MetricLiteral,
    metric_field_ids,
    parse_metric_expression,
)


class MetricServiceError(ValueError):
    pass


class MetricResourceNotFoundError(MetricServiceError):
    pass


class MetricConfigurationError(MetricServiceError):
    pass


class MetricConflictError(MetricServiceError):
    pass


@dataclass(frozen=True, slots=True)
class MetricSummary:
    id: UUID
    series_id: UUID
    dataset_id: UUID
    dataset_name: str
    code: str
    name: str
    version: int
    description: str
    result_type: str
    unit: str | None
    status: str
    owner_name: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MetricDetail(MetricSummary):
    formula: MetricExpression
    dimension_field_ids: list[UUID]


@dataclass(frozen=True, slots=True)
class MetricPage:
    items: list[MetricSummary]
    total: int
    offset: int
    limit: int


def list_metrics(
    session: Session,
    *,
    workspace_id: UUID,
    offset: int,
    limit: int,
) -> MetricPage:
    total = session.scalar(
        select(func.count(Metric.id)).where(*_visible_metric_filters(workspace_id))
    )
    rows = session.execute(
        _summary_statement(workspace_id)
        .order_by(Metric.updated_at.desc(), Metric.id.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return MetricPage(
        items=[_summary_from_row(row) for row in rows],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


def get_metric(
    session: Session,
    *,
    workspace_id: UUID,
    metric_id: UUID,
) -> MetricDetail | None:
    row = session.execute(
        _summary_statement(workspace_id).where(Metric.id == metric_id)
    ).one_or_none()
    if row is None:
        return None
    metric = row[0]
    dimensions = session.scalars(
        select(MetricDimension.dataset_field_id)
        .where(MetricDimension.metric_id == metric.id)
        .order_by(MetricDimension.dataset_field_id)
    ).all()
    summary = _summary_from_row(row)
    return MetricDetail(
        id=summary.id,
        series_id=summary.series_id,
        dataset_id=summary.dataset_id,
        dataset_name=summary.dataset_name,
        code=summary.code,
        name=summary.name,
        version=summary.version,
        description=summary.description,
        result_type=summary.result_type,
        unit=summary.unit,
        status=summary.status,
        owner_name=summary.owner_name,
        updated_at=summary.updated_at,
        formula=parse_metric_expression(metric.formula),
        dimension_field_ids=list(dimensions),
    )


def create_metric(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    request: CreateMetric,
) -> MetricDetail:
    try:
        with session.begin():
            _require_actor(session, workspace_id=workspace_id, actor_user_id=actor_user_id)
            dataset = _require_dataset(
                session,
                workspace_id=workspace_id,
                dataset_id=request.dataset_id,
                metric_status=request.status,
            )
            fields = _validate_fields(
                session,
                dataset=dataset,
                formula=request.formula,
                dimension_field_ids=request.dimension_field_ids,
            )
            _ensure_code_version_available(
                session,
                workspace_id=workspace_id,
                code=request.code,
                version=1,
            )
            metric = Metric(
                workspace_id=workspace_id,
                series_id=uuid4(),
                dataset_id=dataset.id,
                code=request.code,
                name=request.name,
                version=1,
                description=request.description,
                formula=request.formula.model_dump(mode="json"),
                result_type=_result_type(request.formula, fields),
                unit=request.unit,
                status=request.status,
                owner_user_id=actor_user_id,
            )
            session.add(metric)
            session.flush()
            _add_dimensions(session, metric.id, request.dimension_field_ids)
            session.flush()
            detail = _required_metric(session, workspace_id=workspace_id, metric_id=metric.id)
    except IntegrityError as exc:
        raise MetricConflictError("Metric version conflicts with an existing resource") from exc
    return detail


def create_metric_version(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    metric_id: UUID,
    request: CreateMetricVersion,
) -> MetricDetail:
    try:
        with session.begin():
            _require_actor(session, workspace_id=workspace_id, actor_user_id=actor_user_id)
            source = session.scalar(
                select(Metric)
                .where(Metric.id == metric_id, *_visible_metric_filters(workspace_id))
                .with_for_update()
            )
            if source is None:
                raise MetricResourceNotFoundError("Metric was not found")
            formula = (
                request.formula
                if request.formula is not None
                else parse_metric_expression(source.formula)
            )
            dimension_field_ids = (
                request.dimension_field_ids
                if request.dimension_field_ids is not None
                else list(
                    session.scalars(
                        select(MetricDimension.dataset_field_id).where(
                            MetricDimension.metric_id == source.id
                        )
                    ).all()
                )
            )
            dataset = _require_dataset(
                session,
                workspace_id=workspace_id,
                dataset_id=source.dataset_id,
                metric_status=request.status,
            )
            fields = _validate_fields(
                session,
                dataset=dataset,
                formula=formula,
                dimension_field_ids=dimension_field_ids,
            )
            latest_version = session.scalar(
                select(func.max(Metric.version)).where(
                    Metric.workspace_id == workspace_id,
                    Metric.series_id == source.series_id,
                )
            )
            next_version = (latest_version or source.version) + 1
            _ensure_code_version_available(
                session,
                workspace_id=workspace_id,
                code=source.code,
                version=next_version,
            )
            metric = Metric(
                workspace_id=workspace_id,
                series_id=source.series_id,
                dataset_id=source.dataset_id,
                code=source.code,
                name=request.name if request.name is not None else source.name,
                version=next_version,
                description=(
                    request.description if request.description is not None else source.description
                ),
                formula=formula.model_dump(mode="json"),
                result_type=_result_type(formula, fields),
                unit=request.unit if "unit" in request.model_fields_set else source.unit,
                status=request.status,
                owner_user_id=actor_user_id,
            )
            session.add(metric)
            session.flush()
            _add_dimensions(session, metric.id, dimension_field_ids)
            session.flush()
            detail = _required_metric(session, workspace_id=workspace_id, metric_id=metric.id)
    except IntegrityError as exc:
        raise MetricConflictError("Metric version conflicts with an existing resource") from exc
    return detail


def _summary_statement(workspace_id: UUID) -> Select[tuple[Metric, str, str]]:
    return (
        select(Metric, Dataset.name, User.display_name)
        .join(Dataset, Dataset.id == Metric.dataset_id)
        .join(User, User.id == Metric.owner_user_id)
        .where(*_visible_metric_filters(workspace_id))
    )


def _visible_metric_filters(workspace_id: UUID) -> tuple[ColumnElement[bool], ...]:
    return (
        Metric.workspace_id == workspace_id,
        Metric.status != "deleted",
        Metric.deleted_at.is_(None),
    )


def _summary_from_row(row: Row[tuple[Metric, str, str]]) -> MetricSummary:
    metric, dataset_name, owner_name = row
    return MetricSummary(
        id=metric.id,
        series_id=metric.series_id,
        dataset_id=metric.dataset_id,
        dataset_name=dataset_name,
        code=metric.code,
        name=metric.name,
        version=metric.version,
        description=metric.description,
        result_type=metric.result_type,
        unit=metric.unit,
        status=metric.status,
        owner_name=owner_name,
        updated_at=metric.updated_at,
    )


def _required_metric(
    session: Session,
    *,
    workspace_id: UUID,
    metric_id: UUID,
) -> MetricDetail:
    metric = get_metric(session, workspace_id=workspace_id, metric_id=metric_id)
    if metric is None:
        raise MetricResourceNotFoundError("Metric was not found")
    return metric


def _require_actor(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
) -> None:
    actor = session.scalar(
        select(User).where(
            User.id == actor_user_id,
            User.workspace_id == workspace_id,
            User.status == "active",
        )
    )
    if actor is None:
        raise MetricResourceNotFoundError("Actor user was not found")


def _require_dataset(
    session: Session,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
    metric_status: Literal["draft", "active"],
) -> Dataset:
    allowed_statuses = ("active",) if metric_status == "active" else ("draft", "active")
    dataset = session.scalar(
        select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.workspace_id == workspace_id,
            Dataset.status.in_(allowed_statuses),
            Dataset.deleted_at.is_(None),
        )
    )
    if dataset is None:
        raise MetricResourceNotFoundError(
            f"Dataset was not found or cannot host a {metric_status} metric"
        )
    return dataset


def _validate_fields(
    session: Session,
    *,
    dataset: Dataset,
    formula: MetricExpression,
    dimension_field_ids: list[UUID],
) -> dict[UUID, DatasetField]:
    formula_ids = metric_field_ids(formula)
    requested_ids = formula_ids | set(dimension_field_ids)
    fields = session.scalars(
        select(DatasetField).where(
            DatasetField.dataset_id == dataset.id,
            DatasetField.id.in_(requested_ids),
        )
    ).all()
    fields_by_id = {field.id: field for field in fields}
    if len(fields_by_id) != len(requested_ids):
        raise MetricConfigurationError("Every metric field must belong to its dataset version")
    for dimension_id in dimension_field_ids:
        if fields_by_id[dimension_id].field_role != "dimension":
            raise MetricConfigurationError("Metric dimensions must use dimension fields")
    _validate_aggregate_fields(formula, fields_by_id)
    return fields_by_id


def _validate_aggregate_fields(
    formula: MetricExpression,
    fields: dict[UUID, DatasetField],
) -> None:
    if isinstance(formula, MetricAggregate):
        field = fields[formula.field_id]
        if formula.function in {
            AggregateFunction.SUM,
            AggregateFunction.AVERAGE,
            AggregateFunction.MINIMUM,
            AggregateFunction.MAXIMUM,
        } and field.data_type not in {"integer", "decimal"}:
            raise MetricConfigurationError(
                f"Aggregate {formula.function.value!r} requires a numeric field"
            )
        if (
            formula.function
            in {
                AggregateFunction.SUM,
                AggregateFunction.AVERAGE,
            }
            and field.field_role != "measure"
        ):
            raise MetricConfigurationError(
                f"Aggregate {formula.function.value!r} requires a measure field"
            )
        return
    if isinstance(formula, MetricLiteral):
        return
    children = (
        (formula.left, formula.right)
        if isinstance(formula, MetricBinary)
        else (formula.numerator, formula.denominator)
    )
    for child in children:
        _validate_aggregate_fields(child, fields)


def _result_type(
    formula: MetricExpression,
    fields: dict[UUID, DatasetField],
) -> Literal["integer", "decimal"]:
    if isinstance(formula, MetricAggregate):
        if formula.function in {
            AggregateFunction.COUNT,
            AggregateFunction.COUNT_DISTINCT,
        }:
            return "integer"
        if formula.function == AggregateFunction.AVERAGE:
            return "decimal"
        return "integer" if fields[formula.field_id].data_type == "integer" else "decimal"
    return "decimal"


def _add_dimensions(session: Session, metric_id: UUID, field_ids: list[UUID]) -> None:
    session.add_all(
        [MetricDimension(metric_id=metric_id, dataset_field_id=field_id) for field_id in field_ids]
    )


def _ensure_code_version_available(
    session: Session,
    *,
    workspace_id: UUID,
    code: str,
    version: int,
) -> None:
    existing = session.scalar(
        select(Metric.id).where(
            Metric.workspace_id == workspace_id,
            Metric.code == code,
            Metric.version == version,
        )
    )
    if existing is not None:
        raise MetricConflictError(f"Metric {code!r} version {version} already exists")
