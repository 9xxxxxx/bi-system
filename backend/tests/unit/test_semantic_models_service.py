from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bi_system.db.base import Base
from bi_system.db.models import ImportColumn, ImportTarget, User
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.modeling.model_contracts import CreateSemanticModel
from bi_system.modeling.semantic_models import (
    SemanticModelNotFoundError,
    SemanticModelValidationError,
    create_semantic_model,
    get_semantic_model,
    list_semantic_models,
    validate_semantic_model,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class ModelResources:
    workspace_id: UUID
    user_id: UUID
    fact_target_id: UUID
    dimension_target_id: UUID
    fact_keys: tuple[UUID, UUID]
    dimension_keys: tuple[UUID, UUID]


@pytest.fixture
def model_store(
    tmp_path: Path,
) -> Iterator[tuple[sessionmaker[Session], ModelResources, Engine]]:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'semantic.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    with session_factory.begin() as session:
        user = User(
            workspace_id=workspace_id,
            username="model.admin",
            display_name="Model Admin",
            password_hash="hash",
            must_change_password=False,
        )
        fact = ImportTarget(
            workspace_id=workspace_id,
            name="Sales fact",
            physical_table_name=f"data_{uuid4().hex}",
            status="active",
        )
        dimension = ImportTarget(
            workspace_id=workspace_id,
            name="City dimension",
            physical_table_name=f"data_{uuid4().hex}",
            status="active",
        )
        session.add_all([user, fact, dimension])
        session.flush()
        fact_columns = tuple(
            ImportColumn(
                target_id=fact.id,
                source_name=name,
                physical_name=physical,
                data_type="string",
                nullable=False,
                ordinal=ordinal,
            )
            for ordinal, (name, physical) in enumerate(
                (("City ID", "city_id"), ("Month", "month_id")),
            )
        )
        dimension_columns = tuple(
            ImportColumn(
                target_id=dimension.id,
                source_name=name,
                physical_name=physical,
                data_type="string",
                nullable=False,
                ordinal=ordinal,
            )
            for ordinal, (name, physical) in enumerate(
                (("City ID", "city_id"), ("Month", "month_id")),
            )
        )
        session.add_all([*fact_columns, *dimension_columns])
        session.flush()
        resources = ModelResources(
            workspace_id=workspace_id,
            user_id=user.id,
            fact_target_id=fact.id,
            dimension_target_id=dimension.id,
            fact_keys=(fact_columns[0].id, fact_columns[1].id),
            dimension_keys=(dimension_columns[0].id, dimension_columns[1].id),
        )
    try:
        yield session_factory, resources, engine
    finally:
        engine.dispose()


def model_request(
    resources: ModelResources,
    *,
    series_id: UUID | None = None,
) -> CreateSemanticModel:
    return CreateSemanticModel.model_validate(
        {
            "name": "Sales semantic model",
            "series_id": str(series_id) if series_id else None,
            "sources": [
                {"target_id": str(resources.fact_target_id), "alias": "sales", "role": "fact"},
                {
                    "target_id": str(resources.dimension_target_id),
                    "alias": "city",
                    "role": "dimension",
                },
            ],
            "joins": [
                {
                    "left_source": "sales",
                    "right_source": "city",
                    "join_type": "left",
                    "cardinality": "many_to_one",
                    "keys": [
                        {
                            "left_column_id": str(left),
                            "right_column_id": str(right),
                        }
                        for left, right in zip(
                            resources.fact_keys,
                            resources.dimension_keys,
                            strict=True,
                        )
                    ],
                },
            ],
        },
    )


def test_service_creates_reads_lists_and_versions_model(
    model_store: tuple[sessionmaker[Session], ModelResources, Engine],
) -> None:
    session_factory, resources, _engine = model_store
    with session_factory() as session:
        first = create_semantic_model(
            session,
            workspace_id=resources.workspace_id,
            actor_user_id=resources.user_id,
            request=model_request(resources),
        )
        second = create_semantic_model(
            session,
            workspace_id=resources.workspace_id,
            actor_user_id=resources.user_id,
            request=model_request(resources, series_id=first.model.series_id),
        )
        stored = get_semantic_model(
            session,
            workspace_id=resources.workspace_id,
            model_id=first.model.id,
        )
        listed = list_semantic_models(session, workspace_id=resources.workspace_id, limit=10)

    assert first.model.version == 1
    assert second.model.version == 2
    assert second.model.series_id == first.model.series_id
    assert stored is not None
    assert len(stored.sources) == 2
    assert len(stored.joins[0].keys) == 2
    assert {model.id for model in listed} == {first.model.id, second.model.id}


def test_service_hides_cross_workspace_source(
    model_store: tuple[sessionmaker[Session], ModelResources, Engine],
) -> None:
    session_factory, resources, _engine = model_store
    other_workspace = uuid4()
    with session_factory.begin() as session:
        foreign_target = ImportTarget(
            workspace_id=other_workspace,
            name="Foreign",
            physical_table_name=f"data_{uuid4().hex}",
            status="active",
        )
        session.add(foreign_target)
        session.flush()
        request = model_request(resources).model_copy(
            update={
                "sources": [
                    model_request(resources).sources[0],
                    model_request(resources)
                    .sources[1]
                    .model_copy(
                        update={"target_id": foreign_target.id},
                    ),
                ],
            },
        )

    with session_factory() as session, pytest.raises(SemanticModelNotFoundError) as error:
        validate_semantic_model(
            session,
            workspace_id=resources.workspace_id,
            actor_user_id=resources.user_id,
            request=request,
        )
    assert error.value.code == "semantic_model_source_not_found"


def test_service_rejects_join_field_from_wrong_source(
    model_store: tuple[sessionmaker[Session], ModelResources, Engine],
) -> None:
    session_factory, resources, _engine = model_store
    payload = model_request(resources).model_dump()
    payload["joins"][0]["keys"][0]["left_column_id"] = resources.dimension_keys[0]
    request = CreateSemanticModel.model_validate(payload)

    with session_factory() as session, pytest.raises(SemanticModelValidationError) as error:
        validate_semantic_model(
            session,
            workspace_id=resources.workspace_id,
            actor_user_id=resources.user_id,
            request=request,
        )
    assert error.value.code == "semantic_model_join_field_mismatch"


def test_service_get_returns_none_across_workspaces(
    model_store: tuple[sessionmaker[Session], ModelResources, Engine],
) -> None:
    session_factory, resources, _engine = model_store
    with session_factory() as session:
        stored = create_semantic_model(
            session,
            workspace_id=resources.workspace_id,
            actor_user_id=resources.user_id,
            request=model_request(resources),
        )
        hidden = get_semantic_model(
            session,
            workspace_id=uuid4(),
            model_id=stored.model.id,
        )
    assert hidden is None
