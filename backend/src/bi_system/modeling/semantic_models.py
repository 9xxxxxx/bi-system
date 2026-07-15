from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from bi_system.db.models import (
    ImportColumn,
    ImportTarget,
    SemanticModel,
    SemanticModelJoin,
    SemanticModelJoinKey,
    SemanticModelSource,
    User,
)
from bi_system.modeling.model_contracts import CreateSemanticModel


class SemanticModelServiceError(ValueError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.action = action


class SemanticModelNotFoundError(SemanticModelServiceError):
    pass


class SemanticModelValidationError(SemanticModelServiceError):
    pass


@dataclass(frozen=True, slots=True)
class StoredSemanticModelJoin:
    join: SemanticModelJoin
    keys: tuple[SemanticModelJoinKey, ...]


@dataclass(frozen=True, slots=True)
class StoredSemanticModel:
    model: SemanticModel
    sources: tuple[SemanticModelSource, ...]
    joins: tuple[StoredSemanticModelJoin, ...]


@dataclass(frozen=True, slots=True)
class ValidatedSemanticModel:
    targets_by_alias: dict[str, ImportTarget]
    columns_by_id: dict[UUID, ImportColumn]
    series_id: UUID
    version: int


def validate_semantic_model(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    request: CreateSemanticModel,
) -> ValidatedSemanticModel:
    actor = session.get(User, actor_user_id)
    if actor is None or actor.workspace_id != workspace_id or actor.status != "active":
        raise SemanticModelNotFoundError(
            "semantic_model_actor_not_found",
            "Model author was not found in the workspace",
            "Use an active workspace member",
        )

    target_ids = {source.target_id for source in request.sources}
    targets = session.scalars(
        select(ImportTarget).where(
            ImportTarget.workspace_id == workspace_id,
            ImportTarget.id.in_(target_ids),
        ),
    ).all()
    targets_by_id = {target.id: target for target in targets}
    if len(targets_by_id) != len(target_ids):
        raise SemanticModelNotFoundError(
            "semantic_model_source_not_found",
            "One or more model sources were not found",
            "Choose active sources from the current workspace",
        )
    if any(target.status != "active" for target in targets):
        raise SemanticModelValidationError(
            "semantic_model_source_inactive",
            "All model sources must be active",
            "Replace archived sources before validating",
        )
    targets_by_alias = {source.alias: targets_by_id[source.target_id] for source in request.sources}

    column_ids = {
        column_id
        for join in request.joins
        for key in join.keys
        for column_id in (key.left_column_id, key.right_column_id)
    }
    columns = session.scalars(select(ImportColumn).where(ImportColumn.id.in_(column_ids))).all()
    columns_by_id = {column.id: column for column in columns}
    if len(columns_by_id) != len(column_ids):
        raise SemanticModelNotFoundError(
            "semantic_model_join_field_not_found",
            "One or more join fields were not found",
            "Choose fields from the selected model sources",
        )

    for join in request.joins:
        left_target = targets_by_alias[join.left_source]
        right_target = targets_by_alias[join.right_source]
        for key in join.keys:
            left_column = columns_by_id[key.left_column_id]
            right_column = columns_by_id[key.right_column_id]
            if left_column.target_id != left_target.id or right_column.target_id != right_target.id:
                raise SemanticModelValidationError(
                    "semantic_model_join_field_mismatch",
                    "Join fields must belong to their declared sources",
                    "Select join fields from the matching source aliases",
                )
            if left_column.data_type != right_column.data_type:
                raise SemanticModelValidationError(
                    "semantic_model_join_type_mismatch",
                    "Join fields must use the same data type",
                    "Choose compatible fields or normalize them during import",
                )

    series_id, version = _next_version(
        session,
        workspace_id=workspace_id,
        requested_series_id=request.series_id,
    )
    conflict = session.scalar(
        select(SemanticModel.id).where(
            SemanticModel.workspace_id == workspace_id,
            SemanticModel.name == request.name,
            SemanticModel.version == version,
        ),
    )
    if conflict is not None:
        raise SemanticModelValidationError(
            "semantic_model_name_conflict",
            "A semantic model with this name and version already exists",
            "Choose another name or create a version in its series",
        )
    return ValidatedSemanticModel(
        targets_by_alias=targets_by_alias,
        columns_by_id=columns_by_id,
        series_id=series_id,
        version=version,
    )


def create_semantic_model(
    session: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    request: CreateSemanticModel,
) -> StoredSemanticModel:
    with session.begin():
        validated = validate_semantic_model(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            request=request,
        )
        model = SemanticModel(
            workspace_id=workspace_id,
            series_id=validated.series_id,
            name=request.name,
            version=validated.version,
            description=request.description,
            status="draft",
            created_by_user_id=actor_user_id,
        )
        session.add(model)
        session.flush()

        sources: list[SemanticModelSource] = []
        for ordinal, source_input in enumerate(request.sources):
            source = SemanticModelSource(
                semantic_model_id=model.id,
                target_id=source_input.target_id,
                alias=source_input.alias,
                source_role=source_input.role.value,
                ordinal=ordinal,
            )
            session.add(source)
            sources.append(source)
        session.flush()
        sources_by_alias = {source.alias: source for source in sources}

        stored_joins: list[StoredSemanticModelJoin] = []
        for ordinal, join_input in enumerate(request.joins):
            model_join = SemanticModelJoin(
                semantic_model_id=model.id,
                left_source_id=sources_by_alias[join_input.left_source].id,
                right_source_id=sources_by_alias[join_input.right_source].id,
                join_type=join_input.join_type.value,
                cardinality=join_input.cardinality.value,
                risk_acknowledged=False,
                ordinal=ordinal,
            )
            session.add(model_join)
            session.flush()
            keys = tuple(
                SemanticModelJoinKey(
                    semantic_model_join_id=model_join.id,
                    left_column_id=key.left_column_id,
                    right_column_id=key.right_column_id,
                    ordinal=key_ordinal,
                )
                for key_ordinal, key in enumerate(join_input.keys)
            )
            session.add_all(keys)
            stored_joins.append(StoredSemanticModelJoin(join=model_join, keys=keys))
        session.flush()

    return StoredSemanticModel(model=model, sources=tuple(sources), joins=tuple(stored_joins))


def list_semantic_models(
    session: Session,
    *,
    workspace_id: UUID,
    limit: int,
) -> list[SemanticModel]:
    return list(
        session.scalars(
            select(SemanticModel)
            .where(
                SemanticModel.workspace_id == workspace_id,
                SemanticModel.status != "deleted",
            )
            .order_by(SemanticModel.updated_at.desc(), SemanticModel.id)
            .limit(limit),
        ).all(),
    )


def get_semantic_model(
    session: Session,
    *,
    workspace_id: UUID,
    model_id: UUID,
) -> StoredSemanticModel | None:
    model = session.get(SemanticModel, model_id)
    if model is None or model.workspace_id != workspace_id or model.status == "deleted":
        return None
    sources = tuple(
        session.scalars(
            select(SemanticModelSource)
            .where(SemanticModelSource.semantic_model_id == model.id)
            .order_by(SemanticModelSource.ordinal),
        ).all(),
    )
    joins = session.scalars(
        select(SemanticModelJoin)
        .where(SemanticModelJoin.semantic_model_id == model.id)
        .order_by(SemanticModelJoin.ordinal),
    ).all()
    stored_joins = tuple(
        StoredSemanticModelJoin(
            join=join,
            keys=tuple(
                session.scalars(
                    select(SemanticModelJoinKey)
                    .where(SemanticModelJoinKey.semantic_model_join_id == join.id)
                    .order_by(SemanticModelJoinKey.ordinal),
                ).all(),
            ),
        )
        for join in joins
    )
    return StoredSemanticModel(model=model, sources=sources, joins=stored_joins)


def _next_version(
    session: Session,
    *,
    workspace_id: UUID,
    requested_series_id: UUID | None,
) -> tuple[UUID, int]:
    if requested_series_id is None:
        return uuid4(), 1
    latest = session.scalar(
        select(SemanticModel)
        .where(
            SemanticModel.workspace_id == workspace_id,
            SemanticModel.series_id == requested_series_id,
        )
        .order_by(SemanticModel.version.desc())
        .limit(1),
    )
    if latest is None:
        raise SemanticModelNotFoundError(
            "semantic_model_series_not_found",
            "Semantic model series was not found",
            "Create a new model or choose an existing series",
        )
    return requested_series_id, latest.version + 1
