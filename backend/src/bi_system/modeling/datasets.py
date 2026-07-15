from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from bi_system.db.models import Dataset, DatasetField, Metric, SemanticModelSource, User


@dataclass(frozen=True, slots=True)
class DatasetSummary:
    id: UUID
    name: str
    description: str | None
    status: str
    source_count: int
    field_count: int
    metric_count: int
    owner_name: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DatasetPage:
    items: list[DatasetSummary]
    total: int
    offset: int
    limit: int


def list_datasets(
    session: Session,
    *,
    workspace_id: UUID,
    offset: int,
    limit: int,
) -> DatasetPage:
    total = session.scalar(
        select(func.count(Dataset.id)).where(*_visible_dataset_filters(workspace_id))
    )
    rows = session.execute(
        _summary_statement(workspace_id)
        .order_by(Dataset.updated_at.desc(), Dataset.id.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return DatasetPage(
        items=[_summary_from_row(row) for row in rows],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


def get_dataset_summary(
    session: Session,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
) -> DatasetSummary | None:
    row = session.execute(
        _summary_statement(workspace_id).where(Dataset.id == dataset_id)
    ).one_or_none()
    return None if row is None else _summary_from_row(row)


def _summary_statement(
    workspace_id: UUID,
) -> Select[tuple[Dataset, str, int, int, int]]:
    source_count = (
        select(func.count(SemanticModelSource.id))
        .where(SemanticModelSource.semantic_model_id == Dataset.semantic_model_id)
        .correlate(Dataset)
        .scalar_subquery()
    )
    field_count = (
        select(func.count(DatasetField.id))
        .where(DatasetField.dataset_id == Dataset.id)
        .correlate(Dataset)
        .scalar_subquery()
    )
    metric_count = (
        select(func.count(Metric.id))
        .where(
            Metric.dataset_id == Dataset.id,
            Metric.status != "deleted",
            Metric.deleted_at.is_(None),
        )
        .correlate(Dataset)
        .scalar_subquery()
    )
    return (
        select(
            Dataset,
            User.display_name,
            source_count,
            field_count,
            metric_count,
        )
        .join(
            User,
            and_(
                User.id == Dataset.created_by_user_id,
                User.workspace_id == Dataset.workspace_id,
            ),
        )
        .where(*_visible_dataset_filters(workspace_id))
    )


def _visible_dataset_filters(workspace_id: UUID) -> tuple[ColumnElement[bool], ...]:
    return (
        Dataset.workspace_id == workspace_id,
        Dataset.status != "deleted",
        Dataset.deleted_at.is_(None),
    )


def _summary_from_row(
    row: Row[tuple[Dataset, str, int, int, int]],
) -> DatasetSummary:
    dataset, owner_name, source_count, field_count, metric_count = row
    return DatasetSummary(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        status=dataset.status,
        source_count=source_count,
        field_count=field_count,
        metric_count=metric_count,
        owner_name=owner_name,
        updated_at=dataset.updated_at,
    )
