from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    and_,
    delete,
    false,
    func,
    not_,
    or_,
    select,
    true,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from bi_system.db.models import (
    Dataset,
    DatasetField,
    Role,
    RowPolicy,
    RowPolicyAssignment,
    User,
)
from bi_system.identity import QueryPrincipal
from bi_system.modeling.compiler import QueryCompilationError, QueryCompiler, ResolvedSource
from bi_system.modeling.expression import FilterExpression, LogicalPredicate
from bi_system.modeling.row_policy_contracts import (
    CreateRowPolicy,
    CreateRowPolicyVersion,
    ReplaceRowPolicyBindings,
)


class RowPolicyConfigurationError(ValueError):
    pass


class RowPolicyResourceNotFoundError(ValueError):
    pass


class RowPolicyConflictError(ValueError):
    pass


class RowPolicyLifecycleError(ValueError):
    pass


class StoredPolicyExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: FilterExpression


@dataclass(frozen=True, slots=True)
class RowPolicyDetail:
    id: UUID
    workspace_id: UUID
    series_id: UUID
    dataset_id: UUID
    name: str
    version: int
    effect: str
    expression: FilterExpression
    status: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    user_ids: list[UUID]
    role_ids: list[UUID]


@dataclass(frozen=True, slots=True)
class RowPolicyPage:
    items: list[RowPolicyDetail]
    total: int
    offset: int
    limit: int


def list_row_policies(
    session: Session,
    *,
    workspace_id: UUID,
    dataset_id: UUID | None,
    offset: int,
    limit: int,
) -> RowPolicyPage:
    filters = list(_visible_policy_filters(workspace_id))
    if dataset_id is not None:
        filters.append(RowPolicy.dataset_id == dataset_id)
    total = session.scalar(select(func.count(RowPolicy.id)).where(*filters)) or 0
    policies = session.scalars(
        select(RowPolicy)
        .where(*filters)
        .order_by(RowPolicy.updated_at.desc(), RowPolicy.id.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return RowPolicyPage(
        items=[_policy_detail(session, policy) for policy in policies],
        total=total,
        offset=offset,
        limit=limit,
    )


def get_row_policy(
    session: Session,
    *,
    workspace_id: UUID,
    row_policy_id: UUID,
) -> RowPolicyDetail | None:
    policy = session.scalar(
        select(RowPolicy).where(
            RowPolicy.id == row_policy_id,
            *_visible_policy_filters(workspace_id),
        )
    )
    return None if policy is None else _policy_detail(session, policy)


def create_row_policy(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    request: CreateRowPolicy,
) -> RowPolicyDetail:
    try:
        with session.begin():
            _require_actor(session, workspace_id=workspace_id, actor_user_id=actor_user_id)
            dataset = _require_dataset(
                session,
                workspace_id=workspace_id,
                dataset_id=request.dataset_id,
            )
            _validate_expression(
                session,
                dataset=dataset,
                expression=request.expression,
            )
            _ensure_name_version_available(
                session,
                dataset_id=dataset.id,
                name=request.name,
                version=1,
            )
            policy = RowPolicy(
                workspace_id=workspace_id,
                series_id=uuid4(),
                dataset_id=dataset.id,
                name=request.name,
                version=1,
                effect=request.effect,
                expression=_dump_expression(request.expression),
                status="draft",
                created_by_user_id=actor_user_id,
            )
            session.add(policy)
            session.flush()
            detail = _policy_detail(session, policy)
    except IntegrityError as exc:
        raise RowPolicyConflictError(
            "Row policy version conflicts with an existing resource"
        ) from exc
    return detail


def create_row_policy_version(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    row_policy_id: UUID,
    request: CreateRowPolicyVersion,
) -> RowPolicyDetail:
    try:
        with session.begin():
            _require_actor(session, workspace_id=workspace_id, actor_user_id=actor_user_id)
            source = session.scalar(
                select(RowPolicy).where(
                    RowPolicy.id == row_policy_id,
                    *_visible_policy_filters(workspace_id),
                )
            )
            if source is None:
                raise RowPolicyResourceNotFoundError("Row policy was not found")
            dataset = _require_dataset(
                session,
                workspace_id=workspace_id,
                dataset_id=source.dataset_id,
                lock=True,
            )
            series = _lock_policy_series(
                session,
                workspace_id=workspace_id,
                series_id=source.series_id,
            )
            source = next(
                (
                    item
                    for item in series
                    if item.id == row_policy_id
                    and item.status != "deleted"
                    and item.deleted_at is None
                ),
                None,
            )
            if source is None:
                raise RowPolicyResourceNotFoundError("Row policy was not found")
            expression = (
                request.expression
                if request.expression is not None
                else _parse_expression(source.expression)
            )
            _validate_expression(session, dataset=dataset, expression=expression)
            next_version = max(item.version for item in series) + 1
            _ensure_name_version_available(
                session,
                dataset_id=source.dataset_id,
                name=source.name,
                version=next_version,
            )
            policy = RowPolicy(
                workspace_id=workspace_id,
                series_id=source.series_id,
                dataset_id=source.dataset_id,
                name=source.name,
                version=next_version,
                effect=request.effect or source.effect,
                expression=_dump_expression(expression),
                status="draft",
                created_by_user_id=actor_user_id,
            )
            session.add(policy)
            session.flush()
            _copy_bindings(session, source_policy_id=source.id, policy_id=policy.id)
            session.flush()
            detail = _policy_detail(session, policy)
    except IntegrityError as exc:
        raise RowPolicyConflictError(
            "Row policy version conflicts with an existing resource"
        ) from exc
    return detail


def replace_row_policy_bindings(
    session: Session,
    *,
    workspace_id: UUID,
    row_policy_id: UUID,
    request: ReplaceRowPolicyBindings,
) -> RowPolicyDetail:
    with session.begin():
        policy = session.scalar(
            select(RowPolicy)
            .where(
                RowPolicy.id == row_policy_id,
                *_visible_policy_filters(workspace_id),
            )
            .with_for_update()
        )
        if policy is None:
            raise RowPolicyResourceNotFoundError("Row policy was not found")
        if policy.status == "active" and not (request.user_ids or request.role_ids):
            raise RowPolicyLifecycleError("An active row policy must keep at least one binding")
        _validate_principals(
            session,
            workspace_id=workspace_id,
            user_ids=request.user_ids,
            role_ids=request.role_ids,
        )
        session.execute(
            delete(RowPolicyAssignment).where(RowPolicyAssignment.row_policy_id == policy.id)
        )
        session.add_all(
            [
                RowPolicyAssignment(row_policy_id=policy.id, user_id=user_id)
                for user_id in request.user_ids
            ]
            + [
                RowPolicyAssignment(row_policy_id=policy.id, role_id=role_id)
                for role_id in request.role_ids
            ]
        )
        session.flush()
        detail = _policy_detail(session, policy)
    return detail


def activate_row_policy(
    session: Session,
    *,
    workspace_id: UUID,
    row_policy_id: UUID,
) -> RowPolicyDetail:
    with session.begin():
        policy = session.scalar(
            select(RowPolicy).where(
                RowPolicy.id == row_policy_id,
                *_visible_policy_filters(workspace_id),
            )
        )
        if policy is None:
            raise RowPolicyResourceNotFoundError("Row policy was not found")
        dataset = _require_dataset(
            session,
            workspace_id=workspace_id,
            dataset_id=policy.dataset_id,
            lock=True,
        )
        series = _lock_policy_series(
            session,
            workspace_id=workspace_id,
            series_id=policy.series_id,
        )
        policy = next(
            (
                item
                for item in series
                if item.id == row_policy_id and item.status != "deleted" and item.deleted_at is None
            ),
            None,
        )
        if policy is None:
            raise RowPolicyResourceNotFoundError("Row policy was not found")
        if policy.status not in {"draft", "active"}:
            raise RowPolicyLifecycleError("Only a draft row policy can be activated")
        binding_count = session.scalar(
            select(func.count(RowPolicyAssignment.id)).where(
                RowPolicyAssignment.row_policy_id == policy.id
            )
        )
        if not binding_count:
            raise RowPolicyLifecycleError(
                "Row policy must have at least one binding before activation"
            )
        expression = _parse_expression(policy.expression)
        _validate_expression(session, dataset=dataset, expression=expression)
        for sibling in series:
            if sibling.status == "active" and sibling.id != policy.id:
                sibling.status = "disabled"
        policy.status = "active"
        session.flush()
        detail = _policy_detail(session, policy)
    return detail


def _visible_policy_filters(workspace_id: UUID) -> tuple[ColumnElement[bool], ...]:
    return (
        RowPolicy.workspace_id == workspace_id,
        RowPolicy.status != "deleted",
        RowPolicy.deleted_at.is_(None),
    )


def _policy_detail(session: Session, policy: RowPolicy) -> RowPolicyDetail:
    assignments = session.scalars(
        select(RowPolicyAssignment).where(RowPolicyAssignment.row_policy_id == policy.id)
    ).all()
    return RowPolicyDetail(
        id=policy.id,
        workspace_id=policy.workspace_id,
        series_id=policy.series_id,
        dataset_id=policy.dataset_id,
        name=policy.name,
        version=policy.version,
        effect=policy.effect,
        expression=_parse_expression(policy.expression),
        status=policy.status,
        created_by_user_id=policy.created_by_user_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
        user_ids=sorted(
            (assignment.user_id for assignment in assignments if assignment.user_id),
            key=str,
        ),
        role_ids=sorted(
            (assignment.role_id for assignment in assignments if assignment.role_id),
            key=str,
        ),
    )


def _require_actor(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
) -> None:
    actor = session.scalar(
        select(User.id).where(
            User.id == actor_user_id,
            User.workspace_id == workspace_id,
            User.status == "active",
        )
    )
    if actor is None:
        raise RowPolicyResourceNotFoundError("Actor user was not found")


def _require_dataset(
    session: Session,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
    lock: bool = False,
) -> Dataset:
    statement = select(Dataset).where(
        Dataset.id == dataset_id,
        Dataset.workspace_id == workspace_id,
        Dataset.status != "deleted",
        Dataset.deleted_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    dataset = session.scalar(statement)
    if dataset is None:
        raise RowPolicyResourceNotFoundError("Dataset was not found")
    return dataset


def _lock_policy_series(
    session: Session,
    *,
    workspace_id: UUID,
    series_id: UUID,
) -> list[RowPolicy]:
    return list(
        session.scalars(
            select(RowPolicy)
            .where(
                RowPolicy.workspace_id == workspace_id,
                RowPolicy.series_id == series_id,
            )
            .order_by(RowPolicy.id)
            .with_for_update()
        ).all()
    )


def _validate_expression(
    session: Session,
    *,
    dataset: Dataset,
    expression: FilterExpression,
) -> None:
    field_ids = _expression_field_ids(expression)
    fields = session.scalars(
        select(DatasetField).where(
            DatasetField.dataset_id == dataset.id,
            DatasetField.id.in_(field_ids),
        )
    ).all()
    if len(fields) != len(field_ids):
        raise RowPolicyConfigurationError(
            "Every row policy field must belong to its dataset version"
        )
    table = Table(
        "row_policy_validation",
        MetaData(),
        *(Column(str(field.id), _field_sql_type(field.data_type)) for field in fields),
    )
    source = ResolvedSource(
        source_id=dataset.id,
        table=table,
        fields={field.id: table.c[str(field.id)] for field in fields},
    )
    compiler = QueryCompiler(dialect_name=session.get_bind().dialect.name)
    try:
        compiler.compile_filter(expression, source)
    except QueryCompilationError as exc:
        raise RowPolicyConfigurationError(str(exc)) from exc


def _expression_field_ids(expression: FilterExpression) -> set[UUID]:
    predicates = (
        expression.predicates if isinstance(expression, LogicalPredicate) else (expression,)
    )
    return {predicate.field_id for predicate in predicates}


def _field_sql_type(data_type: str) -> Any:
    types = {
        "string": String(),
        "integer": Integer(),
        "decimal": Numeric(),
        "boolean": Boolean(),
        "date": Date(),
        "datetime": DateTime(),
    }
    try:
        return types[data_type]
    except KeyError as exc:
        raise RowPolicyConfigurationError(
            f"Unsupported row policy field type {data_type!r}"
        ) from exc


def _validate_principals(
    session: Session,
    *,
    workspace_id: UUID,
    user_ids: list[UUID],
    role_ids: list[UUID],
) -> None:
    found_user_ids = set(
        session.scalars(
            select(User.id).where(
                User.workspace_id == workspace_id,
                User.id.in_(user_ids),
            )
        ).all()
    )
    found_role_ids = set(
        session.scalars(
            select(Role.id).where(
                Role.workspace_id == workspace_id,
                Role.id.in_(role_ids),
            )
        ).all()
    )
    if found_user_ids != set(user_ids) or found_role_ids != set(role_ids):
        raise RowPolicyResourceNotFoundError(
            "Every row policy user and role must belong to the current workspace"
        )


def _copy_bindings(
    session: Session,
    *,
    source_policy_id: UUID,
    policy_id: UUID,
) -> None:
    assignments = session.scalars(
        select(RowPolicyAssignment).where(RowPolicyAssignment.row_policy_id == source_policy_id)
    ).all()
    session.add_all(
        [
            RowPolicyAssignment(
                row_policy_id=policy_id,
                user_id=assignment.user_id,
                role_id=assignment.role_id,
            )
            for assignment in assignments
        ]
    )


def _ensure_name_version_available(
    session: Session,
    *,
    dataset_id: UUID,
    name: str,
    version: int,
) -> None:
    existing = session.scalar(
        select(RowPolicy.id).where(
            RowPolicy.dataset_id == dataset_id,
            RowPolicy.name == name,
            RowPolicy.version == version,
        )
    )
    if existing is not None:
        raise RowPolicyConflictError(f"Row policy {name!r} version {version} already exists")


def _parse_expression(value: object) -> FilterExpression:
    try:
        return StoredPolicyExpression.model_validate({"expression": value}).expression
    except ValidationError as exc:
        raise RowPolicyConfigurationError("Row policy expression is invalid") from exc


def _dump_expression(expression: FilterExpression) -> dict[str, Any]:
    return StoredPolicyExpression(expression=expression).model_dump(mode="json")["expression"]


def resolve_row_policy_predicates(
    session: Session,
    *,
    dataset_id: UUID,
    workspace_id: UUID,
    principal: QueryPrincipal,
    compiler: QueryCompiler,
    source: ResolvedSource,
) -> Sequence[ColumnElement[bool]]:
    policies = session.scalars(
        select(RowPolicy).where(
            RowPolicy.dataset_id == dataset_id,
            RowPolicy.workspace_id == workspace_id,
            RowPolicy.status == "active",
            RowPolicy.deleted_at.is_(None),
        ),
    ).all()
    if not policies:
        return ()

    policy_ids = {policy.id for policy in policies}
    principal_filters: list[ColumnElement[bool]] = [
        RowPolicyAssignment.user_id == principal.user_id,
    ]
    if principal.role_ids:
        principal_filters.append(RowPolicyAssignment.role_id.in_(principal.role_ids))
    assigned_policy_ids = set(
        session.scalars(
            select(RowPolicyAssignment.row_policy_id).where(
                RowPolicyAssignment.row_policy_id.in_(policy_ids),
                or_(*principal_filters),
            ),
        ).all(),
    )
    matched = [policy for policy in policies if policy.id in assigned_policy_ids]
    if not matched:
        return (false(),)

    allow_predicates: list[ColumnElement[bool]] = []
    deny_predicates: list[ColumnElement[bool]] = []
    for policy in matched:
        try:
            expression = StoredPolicyExpression.model_validate(
                {"expression": policy.expression},
            ).expression
            predicate = compiler.compile_filter(expression, source)
        except (ValidationError, QueryCompilationError) as exc:
            raise RowPolicyConfigurationError(
                f"Active row policy {policy.id} has an invalid expression",
            ) from exc
        if policy.effect == "allow":
            allow_predicates.append(predicate)
        else:
            deny_predicates.append(predicate)

    allow = or_(*allow_predicates) if allow_predicates else true()
    deny = not_(or_(*deny_predicates)) if deny_predicates else true()
    return (and_(allow, deny),)
