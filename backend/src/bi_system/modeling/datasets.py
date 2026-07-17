from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
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
from bi_system.modeling.calculated_field_contracts import (
    CalculatedBinary,
    CalculatedExpression,
    CalculatedFieldReference,
    CalculatedLiteral,
    CalculatedSafeDivide,
    CreateCalculatedField,
    calculated_expression_field_ids,
    parse_calculated_expression,
    rewrite_calculated_expression_fields,
)
from bi_system.modeling.dataset_contracts import (
    CreateDataset,
    CreateDatasetVersion,
    SourceDatasetField,
)
from bi_system.modeling.expression import (
    ComparisonPredicate,
    LogicalPredicate,
    NullPredicate,
    SetPredicate,
    TextPredicate,
)


class DatasetResourceNotFoundError(ValueError):
    pass


class DatasetConfigurationError(ValueError):
    pass


class DatasetLifecycleConflictError(ValueError):
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


def create_calculated_field_version(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    dataset_id: UUID,
    request: CreateCalculatedField,
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
            _required_semantic_model(
                session,
                workspace_id=workspace_id,
                semantic_model_id=source_dataset.semantic_model_id,
                lock=True,
            )
            source_fields = list(
                session.scalars(
                    select(DatasetField)
                    .where(DatasetField.dataset_id == source_dataset.id)
                    .order_by(DatasetField.ordinal, DatasetField.id)
                ).all()
            )
            if len(source_fields) >= 500:
                raise DatasetConfigurationError("Dataset may contain at most 500 fields")
            if any(field.name == request.name for field in source_fields):
                raise DatasetConfigurationError(
                    f"Dataset field name {request.name!r} already exists"
                )
            validate_calculated_field_graph(source_fields)
            source_field_types = {field.id: field.data_type for field in source_fields}
            _validate_calculated_expression(
                request.expression,
                field_types=source_field_types,
                declared_type=request.data_type,
            )
            if request.role == "measure" and request.data_type not in {"integer", "decimal"}:
                raise DatasetConfigurationError("Measure calculated fields must be numeric")

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
            field_id_map = _copy_fields(
                session,
                source_dataset_id=source_dataset.id,
                dataset_id=dataset.id,
            )
            rewritten_expression = rewrite_calculated_expression_fields(
                request.expression,
                field_id_map,
            )
            session.add(
                DatasetField(
                    dataset_id=dataset.id,
                    name=request.name,
                    label=request.label,
                    field_kind="calculated",
                    field_role=request.role,
                    data_type=request.data_type,
                    expression=rewritten_expression.model_dump(mode="json", by_alias=True),
                    hidden=request.hidden,
                    ordinal=len(source_fields),
                )
            )
            session.flush()
            detail = _required_detail(session, workspace_id=workspace_id, dataset_id=dataset.id)
    except IntegrityError as exc:
        raise DatasetConfigurationError(
            "Dataset version conflicts with an existing resource"
        ) from exc
    return detail


def activate_dataset(
    session: Session,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
) -> DatasetDetail:
    with session.begin():
        dataset = session.scalar(
            select(Dataset)
            .where(
                Dataset.id == dataset_id,
                *_visible_dataset_filters(workspace_id),
            )
            .with_for_update()
        )
        if dataset is None:
            raise DatasetResourceNotFoundError("Dataset was not found")
        if dataset.status not in ("draft", "active"):
            raise DatasetLifecycleConflictError("Only a draft dataset version can be activated")

        semantic_model = session.scalar(
            select(SemanticModel)
            .where(
                SemanticModel.id == dataset.semantic_model_id,
                SemanticModel.workspace_id == workspace_id,
                SemanticModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if semantic_model is None:
            raise DatasetResourceNotFoundError("Semantic model was not found")
        if semantic_model.status != "active":
            raise DatasetLifecycleConflictError(
                "The semantic model must be active before its dataset can be activated"
            )

        field_count = session.scalar(
            select(func.count(DatasetField.id)).where(DatasetField.dataset_id == dataset.id)
        )
        if not field_count:
            raise DatasetLifecycleConflictError(
                "The dataset must contain at least one field before activation"
            )

        active_siblings = session.scalars(
            select(Dataset)
            .where(
                Dataset.workspace_id == workspace_id,
                Dataset.series_id == dataset.series_id,
                Dataset.id != dataset.id,
                Dataset.status == "active",
                Dataset.deleted_at.is_(None),
            )
            .with_for_update()
        ).all()
        for sibling in active_siblings:
            sibling.status = "archived"
        dataset.status = "active"
        session.flush()
        detail = _required_detail(session, workspace_id=workspace_id, dataset_id=dataset.id)
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
) -> dict[UUID, UUID]:
    source_fields = list(
        session.scalars(
            select(DatasetField)
            .where(DatasetField.dataset_id == source_dataset_id)
            .order_by(DatasetField.ordinal, DatasetField.id)
        ).all()
    )
    parsed_expressions = validate_calculated_field_graph(source_fields)
    field_id_map = {field.id: uuid4() for field in source_fields}
    copied_fields: list[DatasetField] = []
    for field in source_fields:
        expression = None
        if field.field_kind == "calculated":
            parsed = parsed_expressions[field.id]
            rewritten = rewrite_calculated_expression_fields(parsed, field_id_map)
            expression = rewritten.model_dump(mode="json", by_alias=True)
        copied_fields.append(
            DatasetField(
                id=field_id_map[field.id],
                dataset_id=dataset_id,
                model_source_id=field.model_source_id,
                source_column_id=field.source_column_id,
                name=field.name,
                label=field.label,
                field_kind=field.field_kind,
                field_role=field.field_role,
                data_type=field.data_type,
                expression=expression,
                format_config=deepcopy(field.format_config),
                hidden=field.hidden,
                ordinal=field.ordinal,
            )
        )
    session.add_all(copied_fields)
    return field_id_map


def validate_calculated_field_graph(
    fields: list[DatasetField],
) -> dict[UUID, CalculatedExpression]:
    fields_by_id = {field.id: field for field in fields}
    if len(fields_by_id) != len(fields):
        raise DatasetConfigurationError("Dataset fields must have unique identifiers")
    parsed: dict[UUID, CalculatedExpression] = {}
    dependencies: dict[UUID, set[UUID]] = {}
    for field in fields:
        if field.field_kind == "source":
            if field.expression is not None:
                raise DatasetConfigurationError("Source fields must not contain expressions")
            continue
        if field.field_kind != "calculated" or field.expression is None:
            raise DatasetConfigurationError("Calculated fields require a valid expression")
        try:
            expression = parse_calculated_expression(field.expression)
        except ValueError as exc:
            raise DatasetConfigurationError(
                f"Calculated field {field.name!r} has an invalid expression"
            ) from exc
        referenced_ids = set(calculated_expression_field_ids(expression))
        missing_ids = referenced_ids - fields_by_id.keys()
        if missing_ids:
            raise DatasetConfigurationError(
                f"Calculated field {field.name!r} references a missing dataset field"
            )
        parsed[field.id] = expression
        dependencies[field.id] = {
            field_id
            for field_id in referenced_ids
            if fields_by_id[field_id].field_kind == "calculated"
        }

    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(field_id: UUID) -> None:
        if field_id in visiting:
            raise DatasetConfigurationError("Calculated field dependencies contain a cycle")
        if field_id in visited:
            return
        visiting.add(field_id)
        for dependency_id in dependencies.get(field_id, set()):
            visit(dependency_id)
        visiting.remove(field_id)
        visited.add(field_id)

    for field_id in dependencies:
        visit(field_id)

    resolved_types = {field.id: field.data_type for field in fields if field.field_kind == "source"}

    def validate_type(field_id: UUID) -> None:
        if field_id in resolved_types:
            return
        for dependency_id in dependencies.get(field_id, set()):
            validate_type(dependency_id)
        field = fields_by_id[field_id]
        _validate_calculated_expression(
            parsed[field_id],
            field_types=resolved_types,
            declared_type=field.data_type,
        )
        resolved_types[field_id] = field.data_type

    for field_id in dependencies:
        validate_type(field_id)
    return parsed


def _validate_calculated_expression(
    expression: CalculatedExpression,
    *,
    field_types: dict[UUID, str],
    declared_type: str,
) -> None:
    referenced_ids = calculated_expression_field_ids(expression)
    if not referenced_ids.issubset(field_types):
        raise DatasetConfigurationError(
            "Calculated expression must reference fields from the current dataset version"
        )
    inferred = _infer_calculated_type(
        expression,
        field_types=field_types,
        expected_type=declared_type,
    )
    if inferred == "null":
        return
    if inferred == "integer" and declared_type == "decimal":
        return
    if inferred != declared_type:
        raise DatasetConfigurationError(
            f"Calculated expression type {inferred!r} is incompatible with {declared_type!r}"
        )


def _infer_calculated_type(
    expression: CalculatedExpression,
    *,
    field_types: dict[UUID, str],
    expected_type: str | None = None,
) -> str:
    if isinstance(expression, CalculatedFieldReference):
        field_type = field_types.get(expression.field_id)
        if field_type is None:
            raise DatasetConfigurationError("Calculated expression references a missing field")
        return field_type
    if isinstance(expression, CalculatedLiteral):
        return _literal_data_type(expression.value, expected_type=expected_type)
    if isinstance(expression, CalculatedBinary):
        left_type = _infer_calculated_type(expression.left, field_types=field_types)
        right_type = _infer_calculated_type(expression.right, field_types=field_types)
        _require_numeric_types(left_type, right_type)
        return "decimal" if "decimal" in {left_type, right_type} else "integer"
    if isinstance(expression, CalculatedSafeDivide):
        numerator_type = _infer_calculated_type(expression.numerator, field_types=field_types)
        denominator_type = _infer_calculated_type(expression.denominator, field_types=field_types)
        _require_numeric_types(numerator_type, denominator_type)
        if expression.fallback is not None:
            _literal_data_type(expression.fallback, expected_type="decimal")
        return "decimal"
    _validate_filter_types(expression.when, field_types=field_types)
    then_type = _infer_calculated_type(
        expression.then,
        field_types=field_types,
        expected_type=expected_type,
    )
    else_type = _infer_calculated_type(
        expression.else_,
        field_types=field_types,
        expected_type=expected_type,
    )
    return _merge_case_types(then_type, else_type)


def _literal_data_type(
    value: bool | int | float | Decimal | date | datetime | str | None,
    *,
    expected_type: str | None,
) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise DatasetConfigurationError("Calculated numeric literals must be finite")
        return "decimal"
    if isinstance(value, float):
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite():
            raise DatasetConfigurationError("Calculated numeric literals must be finite")
        return "decimal"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if expected_type == "date":
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise DatasetConfigurationError("Calculated date literal is invalid") from exc
        return "date"
    if expected_type == "datetime":
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise DatasetConfigurationError("Calculated datetime literal is invalid") from exc
        return "datetime"
    return "string"


def _require_numeric_types(*data_types: str) -> None:
    if any(data_type not in {"integer", "decimal"} for data_type in data_types):
        raise DatasetConfigurationError("Calculated arithmetic requires numeric expressions")


def _merge_case_types(left_type: str, right_type: str) -> str:
    if left_type == "null":
        return right_type
    if right_type == "null":
        return left_type
    if {left_type, right_type} == {"integer", "decimal"}:
        return "decimal"
    if left_type != right_type:
        raise DatasetConfigurationError("CASE branches must use compatible data types")
    return left_type


def _validate_filter_types(
    expression: ComparisonPredicate
    | NullPredicate
    | SetPredicate
    | TextPredicate
    | LogicalPredicate,
    *,
    field_types: dict[UUID, str],
) -> None:
    predicates = (
        expression.predicates if isinstance(expression, LogicalPredicate) else (expression,)
    )
    for predicate in predicates:
        field_type = field_types.get(predicate.field_id)
        if field_type is None:
            raise DatasetConfigurationError("CASE condition references a missing field")
        if isinstance(predicate, TextPredicate) and field_type != "string":
            raise DatasetConfigurationError("Text predicates require string fields")
        if isinstance(predicate, ComparisonPredicate):
            value_type = _literal_data_type(predicate.value, expected_type=field_type)
            if not _types_compatible(value_type, field_type):
                raise DatasetConfigurationError("CASE comparison value has an incompatible type")
        if isinstance(predicate, SetPredicate):
            for value in predicate.values:
                value_type = _literal_data_type(value, expected_type=field_type)
                if not _types_compatible(value_type, field_type):
                    raise DatasetConfigurationError("CASE set value has an incompatible type")


def _types_compatible(actual: str, expected: str) -> bool:
    return actual == expected or (actual == "integer" and expected == "decimal")
