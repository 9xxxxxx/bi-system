# pyright: reportUnknownMemberType=false
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_database_session, get_query_principal
from bi_system.api.routes.dataset_queries import router
from bi_system.db.base import Base
from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    Role,
    RowPolicy,
    RowPolicyAssignment,
    SemanticModel,
    SemanticModelSource,
    User,
)
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from bi_system.modeling.contracts import DatasetQueryRequest
from bi_system.modeling.query_service import (
    DatasetQueryForbiddenError,
    DatasetQueryNotFoundError,
    DatasetQueryValidationError,
    execute_dataset_query,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, Uuid
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class QueryResources:
    workspace_id: UUID
    user_id: UUID
    other_user_id: UUID
    role_id: UUID
    dataset_id: UUID
    model_id: UUID
    source_id: UUID
    city_field_id: UUID
    amount_field_id: UUID
    department_field_id: UUID
    calculated_field_id: UUID
    batch_ids: tuple[UUID, UUID]


@pytest.fixture
def query_store(
    tmp_path: Path,
) -> Iterator[tuple[sessionmaker[Session], QueryResources, Engine]]:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'query.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    table_name = f"data_{uuid4().hex}"
    table = Table(
        table_name,
        MetaData(),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_active", Boolean, nullable=False),
        Column("city", String),
        Column("amount", Integer),
        Column("department", String),
    )
    table.create(engine)
    batch_ids = (uuid4(), uuid4())
    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            [
                {
                    "_batch_id": batch_ids[0],
                    "_active": True,
                    "city": "北京",
                    "amount": 10,
                    "department": "sales",
                },
                {
                    "_batch_id": batch_ids[0],
                    "_active": True,
                    "city": "北京",
                    "amount": 20,
                    "department": "secret",
                },
                {
                    "_batch_id": batch_ids[0],
                    "_active": True,
                    "city": "上海",
                    "amount": 30,
                    "department": "sales",
                },
                {
                    "_batch_id": batch_ids[1],
                    "_active": True,
                    "city": "北京",
                    "amount": 5,
                    "department": "sales",
                },
                {
                    "_batch_id": batch_ids[1],
                    "_active": False,
                    "city": "北京",
                    "amount": 999,
                    "department": "sales",
                },
            ],
        )

    with session_factory.begin() as session:
        user = User(
            workspace_id=workspace_id,
            username="query.user",
            display_name="Query User",
            password_hash="hash",
            must_change_password=False,
        )
        other_user = User(
            workspace_id=workspace_id,
            username="other.user",
            display_name="Other User",
            password_hash="hash",
            must_change_password=False,
        )
        role = Role(
            workspace_id=workspace_id,
            code="analyst",
            name="Analyst",
            permissions=["datasets:query"],
        )
        target = ImportTarget(
            workspace_id=workspace_id,
            name="Sales",
            physical_table_name=table_name,
            status="active",
        )
        session.add_all([user, other_user, role, target])
        session.flush()
        import_columns = [
            ImportColumn(
                target_id=target.id,
                source_name=name.title(),
                physical_name=name,
                data_type=data_type,
                nullable=True,
                ordinal=ordinal,
            )
            for ordinal, (name, data_type) in enumerate(
                (("city", "string"), ("amount", "integer"), ("department", "string")),
            )
        ]
        session.add_all(import_columns)
        session.flush()
        model = SemanticModel(
            workspace_id=workspace_id,
            name="Sales model",
            version=1,
            status="active",
            created_by_user_id=user.id,
        )
        session.add(model)
        session.flush()
        source = SemanticModelSource(
            semantic_model_id=model.id,
            target_id=target.id,
            alias="sales",
            source_role="fact",
            ordinal=0,
        )
        session.add(source)
        session.flush()
        dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=model.id,
            name="Sales dataset",
            version=1,
            status="active",
            created_by_user_id=user.id,
        )
        session.add(dataset)
        session.flush()
        fields = [
            DatasetField(
                dataset_id=dataset.id,
                model_source_id=source.id,
                source_column_id=column.id,
                name=column.physical_name,
                label=column.source_name,
                field_kind="source",
                field_role="measure" if column.physical_name == "amount" else "dimension",
                data_type=column.data_type,
                hidden=False,
                ordinal=ordinal,
            )
            for ordinal, column in enumerate(import_columns)
        ]
        calculated = DatasetField(
            dataset_id=dataset.id,
            name="double_amount",
            label="Double amount",
            field_kind="calculated",
            field_role="measure",
            data_type="integer",
            expression={"op": "multiply", "value": 2},
            hidden=False,
            ordinal=3,
        )
        session.add_all([*fields, calculated])
        session.flush()
        resources = QueryResources(
            workspace_id=workspace_id,
            user_id=user.id,
            other_user_id=other_user.id,
            role_id=role.id,
            dataset_id=dataset.id,
            model_id=model.id,
            source_id=source.id,
            city_field_id=fields[0].id,
            amount_field_id=fields[1].id,
            department_field_id=fields[2].id,
            calculated_field_id=calculated.id,
            batch_ids=batch_ids,
        )
    try:
        yield session_factory, resources, engine
    finally:
        engine.dispose()


def principal(resources: QueryResources, *, permitted: bool = True) -> QueryPrincipal:
    return QueryPrincipal(
        user_id=resources.user_id,
        workspace_id=resources.workspace_id,
        role_ids=frozenset({resources.role_id}),
        permissions=frozenset({"datasets:query"}) if permitted else frozenset(),
    )


def detail_request(resources: QueryResources, *, limit: int = 500) -> DatasetQueryRequest:
    return DatasetQueryRequest.model_validate(
        {
            "dataset_id": str(resources.dataset_id),
            "selections": [
                {"field_id": str(resources.city_field_id), "output_name": "city"},
                {"field_id": str(resources.amount_field_id), "output_name": "amount"},
            ],
            "order_by": [
                {"field_id": str(resources.amount_field_id), "direction": "asc"},
            ],
            "limit": limit,
        },
    )


def test_query_is_bounded_and_returns_active_batch_context(
    query_store: tuple[sessionmaker[Session], QueryResources, Engine],
) -> None:
    session_factory, resources, _engine = query_store
    with session_factory() as session:
        result = execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources, limit=2),
        )

    assert result.columns == ("city", "amount")
    assert result.rows == (
        {"city": "北京", "amount": 5},
        {"city": "北京", "amount": 10},
    )
    assert result.truncated is True
    assert set(result.source_batch_ids) == set(resources.batch_ids)
    assert result.dataset_version == 1
    assert result.elapsed_ms >= 0


def test_source_batch_context_includes_user_filter(
    query_store: tuple[sessionmaker[Session], QueryResources, Engine],
) -> None:
    session_factory, resources, _engine = query_store
    payload = detail_request(resources).model_dump(mode="json")
    payload["filter"] = {
        "kind": "comparison",
        "field_id": str(resources.amount_field_id),
        "operator": "eq",
        "value": 5,
    }
    request = DatasetQueryRequest.model_validate(payload)

    with session_factory() as session:
        result = execute_dataset_query(
            session,
            principal=principal(resources),
            request=request,
        )

    assert result.rows == ({"city": "北京", "amount": 5},)
    assert result.source_batch_ids == (resources.batch_ids[1],)


def test_row_policies_combine_allow_or_and_deny_not(
    query_store: tuple[sessionmaker[Session], QueryResources, Engine],
) -> None:
    session_factory, resources, _engine = query_store
    with session_factory.begin() as session:
        allow = RowPolicy(
            workspace_id=resources.workspace_id,
            dataset_id=resources.dataset_id,
            name="Beijing only",
            version=1,
            effect="allow",
            expression={
                "kind": "comparison",
                "field_id": str(resources.city_field_id),
                "operator": "eq",
                "value": "北京",
            },
            status="active",
            created_by_user_id=resources.user_id,
        )
        deny = RowPolicy(
            workspace_id=resources.workspace_id,
            dataset_id=resources.dataset_id,
            name="Hide secret",
            version=1,
            effect="deny",
            expression={
                "kind": "comparison",
                "field_id": str(resources.department_field_id),
                "operator": "eq",
                "value": "secret",
            },
            status="active",
            created_by_user_id=resources.user_id,
        )
        session.add_all([allow, deny])
        session.flush()
        session.add_all(
            [
                RowPolicyAssignment(row_policy_id=allow.id, user_id=resources.user_id),
                RowPolicyAssignment(row_policy_id=deny.id, role_id=resources.role_id),
            ],
        )

    aggregate = DatasetQueryRequest.model_validate(
        {
            "dataset_id": str(resources.dataset_id),
            "selections": [
                {"field_id": str(resources.city_field_id), "output_name": "city"},
                {
                    "field_id": str(resources.amount_field_id),
                    "output_name": "total_amount",
                    "aggregate": "sum",
                },
            ],
            "group_by": [str(resources.city_field_id)],
        },
    )
    with session_factory() as session:
        result = execute_dataset_query(
            session,
            principal=principal(resources),
            request=aggregate,
        )

    assert result.rows == ({"city": "北京", "total_amount": 15},)
    assert set(result.source_batch_ids) == set(resources.batch_ids)


def test_active_policies_without_principal_assignment_return_no_rows(
    query_store: tuple[sessionmaker[Session], QueryResources, Engine],
) -> None:
    session_factory, resources, _engine = query_store
    with session_factory.begin() as session:
        policy = RowPolicy(
            workspace_id=resources.workspace_id,
            dataset_id=resources.dataset_id,
            name="Other user only",
            version=1,
            effect="allow",
            expression={
                "kind": "comparison",
                "field_id": str(resources.city_field_id),
                "operator": "eq",
                "value": "上海",
            },
            status="active",
            created_by_user_id=resources.user_id,
        )
        session.add(policy)
        session.flush()
        session.add(
            RowPolicyAssignment(row_policy_id=policy.id, user_id=resources.other_user_id),
        )

    with session_factory() as session:
        result = execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )
    assert result.rows == ()
    assert result.source_batch_ids == ()


def test_invalid_active_policy_fails_closed(
    query_store: tuple[sessionmaker[Session], QueryResources, Engine],
) -> None:
    session_factory, resources, _engine = query_store
    with session_factory.begin() as session:
        policy = RowPolicy(
            workspace_id=resources.workspace_id,
            dataset_id=resources.dataset_id,
            name="Broken policy",
            version=1,
            effect="allow",
            expression={"raw_sql": "1 = 1"},
            status="active",
            created_by_user_id=resources.user_id,
        )
        session.add(policy)
        session.flush()
        session.add(
            RowPolicyAssignment(row_policy_id=policy.id, user_id=resources.user_id),
        )

    with session_factory() as session, pytest.raises(DatasetQueryValidationError) as error:
        execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )
    assert error.value.code == "row_policy_configuration_invalid"


def test_query_rejects_missing_permission_cross_workspace_and_calculated_field(
    query_store: tuple[sessionmaker[Session], QueryResources, Engine],
) -> None:
    session_factory, resources, _engine = query_store
    with session_factory() as session:
        with pytest.raises(DatasetQueryForbiddenError):
            execute_dataset_query(
                session,
                principal=principal(resources, permitted=False),
                request=detail_request(resources),
            )
        with pytest.raises(DatasetQueryNotFoundError):
            execute_dataset_query(
                session,
                principal=QueryPrincipal(
                    user_id=uuid4(),
                    workspace_id=uuid4(),
                    permissions=frozenset({"datasets:query"}),
                ),
                request=detail_request(resources),
            )
        calculated = DatasetQueryRequest.model_validate(
            {
                "dataset_id": str(resources.dataset_id),
                "selections": [
                    {
                        "field_id": str(resources.calculated_field_id),
                        "output_name": "double_amount",
                    },
                ],
            },
        )
        with pytest.raises(DatasetQueryValidationError) as error:
            execute_dataset_query(
                session,
                principal=principal(resources),
                request=calculated,
            )
    assert error.value.code == "calculated_field_query_unsupported"


def test_query_hides_dataset_when_semantic_model_workspace_is_inconsistent(
    query_store: tuple[sessionmaker[Session], QueryResources, Engine],
) -> None:
    session_factory, resources, _engine = query_store
    with session_factory.begin() as session:
        model = session.get(SemanticModel, resources.model_id)
        assert model is not None
        model.workspace_id = uuid4()

    with session_factory() as session, pytest.raises(DatasetQueryNotFoundError) as error:
        execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )
    assert error.value.code == "dataset_model_not_found"


def test_dataset_query_api_validates_executes_and_returns_structured_errors(
    query_store: tuple[sessionmaker[Session], QueryResources, Engine],
) -> None:
    session_factory, resources, _engine = query_store
    application = FastAPI()
    application.include_router(router, prefix="/dataset-queries")

    def session_dependency() -> Generator[Session]:
        with session_factory() as session:
            yield session

    actor: dict[str, QueryPrincipal] = {"value": principal(resources)}
    application.dependency_overrides[get_database_session] = session_dependency
    application.dependency_overrides[get_query_principal] = lambda: actor["value"]
    payload: dict[str, Any] = detail_request(resources, limit=2).model_dump(mode="json")

    with TestClient(application) as client:
        validated = cast(
            Response,
            client.post("/dataset-queries/validate", json=payload),
        )
        executed = cast(Response, client.post("/dataset-queries", json=payload))
        actor["value"] = principal(resources, permitted=False)
        forbidden = cast(Response, client.post("/dataset-queries", json=payload))
        actor["value"] = principal(resources)
        calculated_payload: dict[str, Any] = {
            "dataset_id": str(resources.dataset_id),
            "selections": [
                {
                    "field_id": str(resources.calculated_field_id),
                    "output_name": "double_amount",
                },
            ],
        }
        invalid = cast(
            Response,
            client.post("/dataset-queries/validate", json=calculated_payload),
        )
        missing_payload = dict(payload)
        missing_payload["dataset_id"] = str(uuid4())
        missing = cast(Response, client.post("/dataset-queries", json=missing_payload))

    assert validated.status_code == 200
    assert validated.json()["columns"] == ["city", "amount"]
    assert executed.status_code == 200
    assert executed.json()["truncated"] is True
    assert len(executed.json()["source_batch_ids"]) == 2
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "dataset_query_forbidden"
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "calculated_field_query_unsupported"
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "dataset_not_found"
