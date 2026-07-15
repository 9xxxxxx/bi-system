from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, func, select
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    Metric,
    SemanticModel,
    SemanticModelSource,
    User,
)
from bi_system.modeling.dataset_contracts import (
    CreateDataset,
    CreateDatasetVersion,
    SourceDatasetField,
)


class DatasetResourceNotFoundError(ValueError):
    pass


class DatasetConfigurationError(ValueError):
    pass


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


@dataclass(frozen=True, slots=True)
class DatasetFieldDetail:
    id: UUID
    model_source_id: UUID | None
    source_column_id: UUID | None
    name: str
    label: str
    field_kind: str
    role: str
    data_type: str
    hidden: bool
    ordinal: int


@dataclass(frozen=True, slots=True)
class DatasetDetail(DatasetSummary):
    semantic_model_id: UUID
    series_id: UUID
    version: int
    fields: list[DatasetFieldDetail]


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


def get_dataset_detail(
    session: Session,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
) -> DatasetDetail | None:
    row = session.execute(
        _summary_statement(workspace_id).where(Dataset.id == dataset_id)
    ).one_or_none()
    if row is None:
        return None
    return _detail_from_row(session, row)


def create_dataset(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    request: CreateDataset,
) -> DatasetDetail:
    try:
        with session.begin():
            _required_actor_user(
                session,
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            semantic_model = _required_semantic_model(
                session,
                workspace_id=workspace_id,
                semantic_model_id=request.semantic_model_id,
            )
            _ensure_name_version_available(
                session,
                workspace_id=workspace_id,
                name=request.name,
                version=1,
            )
            dataset = Dataset(
                workspace_id=workspace_id,
                series_id=uuid4(),
                semantic_model_id=semantic_model.id,
                name=request.name,
                version=1,
                description=request.description,
                status="draft",
                created_by_user_id=actor_user_id,
            )
            session.add(dataset)
            session.flush()
            _add_source_fields(
                session,
                dataset=dataset,
                semantic_model=semantic_model,
                fields=request.fields,
            )
            session.flush()
            detail = _required_detail(session, workspace_id=workspace_id, dataset_id=dataset.id)
    except IntegrityError as exc:
        raise DatasetConfigurationError(
            "Dataset version conflicts with an existing resource"
        ) from exc
    return detail


def create_dataset_version(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    dataset_id: UUID,
    request: CreateDatasetVersion,
) -> DatasetDetail:
    try:
        with session.begin():
            _required_actor_user(
                session,
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            source_dataset = session.scalar(
                select(Dataset)
                .where(
                    Dataset.id == dataset_id,
                    *_visible_dataset_filters(workspace_id),
                )
                .with_for_update()
            )
            if source_dataset is None:
                raise DatasetResourceNotFoundError("Dataset was not found")
            semantic_model = _required_semantic_model(
                session,
                workspace_id=workspace_id,
                semantic_model_id=source_dataset.semantic_model_id,
                lock=True,
            )
            latest_version = session.scalar(
                select(func.max(Dataset.version)).where(
                    Dataset.workspace_id == workspace_id,
                    Dataset.series_id == source_dataset.series_id,
                )
            )
            next_version = (latest_version or source_dataset.version) + 1
            _ensure_name_version_available(
                session,
                workspace_id=workspace_id,
                name=source_dataset.name,
                version=next_version,
            )
            dataset = Dataset(
                workspace_id=workspace_id,
                series_id=source_dataset.series_id,
                semantic_model_id=source_dataset.semantic_model_id,
                name=source_dataset.name,
                version=next_version,
                description=source_dataset.description,
                status="draft",
                created_by_user_id=actor_user_id,
            )
            session.add(dataset)
            session.flush()
            if request.fields is None:
                _copy_fields(session, source_dataset_id=source_dataset.id, dataset_id=dataset.id)
            else:
                _add_source_fields(
                    session,
                    dataset=dataset,
                    semantic_model=semantic_model,
                    fields=request.fields,
                )
            session.flush()
            detail = _required_detail(session, workspace_id=workspace_id, dataset_id=dataset.id)
    except IntegrityError as exc:
        raise DatasetConfigurationError(
            "Dataset version conflicts with an existing resource"
        ) from exc
    return detail


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


def _detail_from_row(
    session: Session,
    row: Row[tuple[Dataset, str, int, int, int]],
) -> DatasetDetail:
    dataset = row[0]
    summary = _summary_from_row(row)
    fields = session.scalars(
        select(DatasetField)
        .where(DatasetField.dataset_id == dataset.id)
        .order_by(DatasetField.ordinal, DatasetField.id)
    ).all()
    return DatasetDetail(
        id=summary.id,
        name=summary.name,
        description=summary.description,
        status=summary.status,
        source_count=summary.source_count,
        field_count=summary.field_count,
        metric_count=summary.metric_count,
        owner_name=summary.owner_name,
        updated_at=summary.updated_at,
        semantic_model_id=dataset.semantic_model_id,
        series_id=dataset.series_id,
        version=dataset.version,
        fields=[
            DatasetFieldDetail(
                id=field.id,
                model_source_id=field.model_source_id,
                source_column_id=field.source_column_id,
                name=field.name,
                label=field.label,
                field_kind=field.field_kind,
                role=field.field_role,
                data_type=field.data_type,
                hidden=field.hidden,
                ordinal=field.ordinal,
            )
            for field in fields
        ],
    )


def _required_detail(
    session: Session,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
) -> DatasetDetail:
    detail = get_dataset_detail(
        session,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
    )
    if detail is None:
        raise DatasetResourceNotFoundError("Dataset was not found")
    return detail


def _required_semantic_model(
    session: Session,
    *,
    workspace_id: UUID,
    semantic_model_id: UUID,
    lock: bool = False,
) -> SemanticModel:
    query = select(SemanticModel).where(
        SemanticModel.id == semantic_model_id,
        SemanticModel.workspace_id == workspace_id,
        SemanticModel.status.in_(("draft", "active")),
        SemanticModel.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    semantic_model = session.scalar(query)
    if semantic_model is None:
        raise DatasetResourceNotFoundError("Semantic model was not found")
    return semantic_model


def _required_actor_user(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
) -> User:
    actor = session.scalar(
        select(User).where(
            User.id == actor_user_id,
            User.workspace_id == workspace_id,
        )
    )
    if actor is None:
        raise DatasetResourceNotFoundError("Actor user was not found")
    return actor


def _ensure_name_version_available(
    session: Session,
    *,
    workspace_id: UUID,
    name: str,
    version: int,
) -> None:
    existing_id = session.scalar(
        select(Dataset.id).where(
            Dataset.workspace_id == workspace_id,
            Dataset.name == name,
            Dataset.version == version,
        )
    )
    if existing_id is not None:
        raise DatasetConfigurationError(f"Dataset {name!r} version {version} already exists")


def _add_source_fields(
    session: Session,
    *,
    dataset: Dataset,
    semantic_model: SemanticModel,
    fields: list[SourceDatasetField],
) -> None:
    source_ids = {field.model_source_id for field in fields}
    sources = session.scalars(
        select(SemanticModelSource).where(
            SemanticModelSource.semantic_model_id == semantic_model.id,
            SemanticModelSource.id.in_(source_ids),
        )
    ).all()
    sources_by_id = {source.id: source for source in sources}
    if len(sources_by_id) != len(source_ids):
        raise DatasetConfigurationError(
            "Every dataset field must use a source from the semantic model"
        )

    column_ids = {field.source_column_id for field in fields}
    columns = session.scalars(select(ImportColumn).where(ImportColumn.id.in_(column_ids))).all()
    columns_by_id = {column.id: column for column in columns}
    if len(columns_by_id) != len(column_ids):
        raise DatasetConfigurationError("Every dataset field must use an available column")

    stored_fields: list[DatasetField] = []
    for ordinal, field in enumerate(fields):
        source = sources_by_id[field.model_source_id]
        column = columns_by_id[field.source_column_id]
        if column.target_id != source.target_id:
            raise DatasetConfigurationError(
                f"Source column for field {field.name!r} does not belong to its model source"
            )
        stored_fields.append(
            DatasetField(
                dataset_id=dataset.id,
                model_source_id=source.id,
                source_column_id=column.id,
                name=field.name,
                label=field.label,
                field_kind="source",
                field_role=field.role,
                data_type=column.data_type,
                hidden=field.hidden,
                ordinal=ordinal,
            )
        )
    session.add_all(stored_fields)


def _copy_fields(
    session: Session,
    *,
    source_dataset_id: UUID,
    dataset_id: UUID,
) -> None:
    source_fields = session.scalars(
        select(DatasetField)
        .where(DatasetField.dataset_id == source_dataset_id)
        .order_by(DatasetField.ordinal, DatasetField.id)
    ).all()
    session.add_all(
        [
            DatasetField(
                dataset_id=dataset_id,
                model_source_id=field.model_source_id,
                source_column_id=field.source_column_id,
                name=field.name,
                label=field.label,
                field_kind=field.field_kind,
                field_role=field.field_role,
                data_type=field.data_type,
                expression=deepcopy(field.expression),
                format_config=deepcopy(field.format_config),
                hidden=field.hidden,
                ordinal=field.ordinal,
            )
            for field in source_fields
        ]
    )
