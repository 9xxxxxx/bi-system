from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import and_, false, not_, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from bi_system.db.models import RowPolicy, RowPolicyAssignment
from bi_system.identity import QueryPrincipal
from bi_system.modeling.compiler import QueryCompilationError, QueryCompiler, ResolvedSource
from bi_system.modeling.expression import FilterExpression


class RowPolicyConfigurationError(ValueError):
    pass


class StoredPolicyExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: FilterExpression


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
