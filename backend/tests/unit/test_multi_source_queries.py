# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bi_system.db.base import Base
from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    Metric,
    MetricDimension,
    RowPolicy,
    RowPolicyAssignment,
    SemanticModel,
    SemanticModelJoin,
    SemanticModelJoinKey,
    SemanticModelSource,
    User,
)
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from bi_system.modeling.contracts import DatasetQueryRequest
from bi_system.modeling.query_service import (
    DatasetQueryValidationError,
    execute_dataset_query,
)
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, Uuid, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class MultiSourceResources:
    workspace_id: UUID
    user_id: UUID
    dataset_id: UUID
    city_source_id: UUID
    product_source_id: UUID
    city_join_id: UUID
    product_join_id: UUID
    city_right_key_id: UUID
    product_id_column_id: UUID
    city_field_id: UUID
    product_field_id: UUID
    amount_field_id: UUID
    department_field_id: UUID
    metric_id: UUID
    fact_batch_id: UUID
    city_batch_id: UUID
    product_batch_id: UUID


@pytest.fixture
def multi_source_store(
    tmp_path: Path,
) -> Iterator[tuple[sessionmaker[Session], MultiSourceResources, Engine]]:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'multi-source.db').as_posix()}"
    )
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    fact_name = f"data_{uuid4().hex}"
    city_name = f"data_{uuid4().hex}"
    product_name = f"data_{uuid4().hex}"
    fact_table = Table(
        fact_name,
        MetaData(),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_active", Boolean, nullable=False),
        Column("city_id", String),
        Column("tenant", String),
        Column("product_id", String),
        Column("amount", Integer),
        Column("department", String),
    )
    city_table = Table(
        city_name,
        MetaData(),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_active", Boolean, nullable=False),
        Column("city_id", String),
        Column("tenant", String),
        Column("city_name", String),
    )
    product_table = Table(
        product_name,
        MetaData(),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_active", Boolean, nullable=False),
        Column("product_id", String),
        Column("product_name", String),
    )
    fact_table.create(engine)
    city_table.create(engine)
    product_table.create(engine)
    fact_batch_id, city_batch_id, product_batch_id = uuid4(), uuid4(), uuid4()
    inactive_city_batch, inactive_product_batch = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            fact_table.insert(),
            [
                {
                    "_batch_id": fact_batch_id,
                    "_active": True,
                    "city_id": "1",
                    "tenant": "A",
                    "product_id": "P1",
                    "amount": 10,
                    "department": "sales",
                },
                {
                    "_batch_id": fact_batch_id,
                    "_active": True,
                    "city_id": "2",
                    "tenant": "A",
                    "product_id": "P1",
                    "amount": 20,
                    "department": "secret",
                },
                {
                    "_batch_id": fact_batch_id,
                    "_active": True,
                    "city_id": "3",
                    "tenant": "A",
                    "product_id": "P1",
                    "amount": 30,
                    "department": "sales",
                },
                {
                    "_batch_id": fact_batch_id,
                    "_active": True,
                    "city_id": "1",
                    "tenant": "A",
                    "product_id": "P2",
                    "amount": 40,
                    "department": "sales",
                },
                {
                    "_batch_id": fact_batch_id,
                    "_active": False,
                    "city_id": "1",
                    "tenant": "A",
                    "product_id": "P1",
                    "amount": 999,
                    "department": "sales",
                },
            ],
        )
        connection.execute(
            city_table.insert(),
            [
                {
                    "_batch_id": city_batch_id,
                    "_active": True,
                    "city_id": "1",
                    "tenant": "A",
                    "city_name": "Beijing",
                },
                {
                    "_batch_id": uuid4(),
                    "_active": True,
                    "city_id": "1",
                    "tenant": "B",
                    "city_name": "Wrong tenant",
                },
                {
                    "_batch_id": inactive_city_batch,
                    "_active": False,
                    "city_id": "2",
                    "tenant": "A",
                    "city_name": "Shanghai",
                },
            ],
        )
        connection.execute(
            product_table.insert(),
            [
                {
                    "_batch_id": product_batch_id,
                    "_active": True,
                    "product_id": "P1",
                    "product_name": "Widget",
                },
                {
                    "_batch_id": inactive_product_batch,
                    "_active": False,
                    "product_id": "P2",
                    "product_name": "Hidden product",
                },
            ],
        )

    with session_factory.begin() as session:
        user = User(
            workspace_id=workspace_id,
            username="multi.query",
            display_name="Multi Query",
            password_hash="hash",
            must_change_password=False,
        )
        targets = [
            ImportTarget(
                workspace_id=workspace_id,
                name=name,
                physical_table_name=table_name,
                status="active",
            )
            for name, table_name in (
                ("Sales fact", fact_name),
                ("City dimension", city_name),
                ("Product dimension", product_name),
            )
        ]
        session.add_all([user, *targets])
        session.flush()
        column_specs = (
            (
                targets[0],
                (
                    ("city_id", "string"),
                    ("tenant", "string"),
                    ("product_id", "string"),
                    ("amount", "integer"),
                    ("department", "string"),
                ),
            ),
            (
                targets[1],
                (("city_id", "string"), ("tenant", "string"), ("city_name", "string")),
            ),
            (
                targets[2],
                (("product_id", "string"), ("product_name", "string")),
            ),
        )
        columns_by_target: dict[UUID, dict[str, ImportColumn]] = {}
        for target, specs in column_specs:
            columns = {
                name: ImportColumn(
                    target_id=target.id,
                    source_name=name,
                    physical_name=name,
                    data_type=data_type,
                    nullable=True,
                    ordinal=ordinal,
                )
                for ordinal, (name, data_type) in enumerate(specs)
            }
            session.add_all(columns.values())
            columns_by_target[target.id] = columns
        session.flush()
        model = SemanticModel(
            workspace_id=workspace_id,
            name="Sales star",
            version=1,
            status="active",
            created_by_user_id=user.id,
        )
        session.add(model)
        session.flush()
        fact_source = SemanticModelSource(
            semantic_model_id=model.id,
            target_id=targets[0].id,
            alias="sales",
            source_role="fact",
            ordinal=0,
        )
        city_source = SemanticModelSource(
            semantic_model_id=model.id,
            target_id=targets[1].id,
            alias="city",
            source_role="dimension",
            ordinal=1,
        )
        product_source = SemanticModelSource(
            semantic_model_id=model.id,
            target_id=targets[2].id,
            alias="product",
            source_role="dimension",
            ordinal=2,
        )
        session.add_all([fact_source, city_source, product_source])
        session.flush()
        city_join = SemanticModelJoin(
            semantic_model_id=model.id,
            left_source_id=fact_source.id,
            right_source_id=city_source.id,
            join_type="left",
            cardinality="many_to_one",
            ordinal=0,
        )
        product_join = SemanticModelJoin(
            semantic_model_id=model.id,
            left_source_id=fact_source.id,
            right_source_id=product_source.id,
            join_type="inner",
            cardinality="many_to_one",
            ordinal=1,
        )
        session.add_all([city_join, product_join])
        session.flush()
        fact_columns = columns_by_target[targets[0].id]
        city_columns = columns_by_target[targets[1].id]
        product_columns = columns_by_target[targets[2].id]
        city_keys = [
            SemanticModelJoinKey(
                semantic_model_join_id=city_join.id,
                left_column_id=fact_columns[name].id,
                right_column_id=city_columns[name].id,
                ordinal=ordinal,
            )
            for ordinal, name in enumerate(("city_id", "tenant"))
        ]
        product_key = SemanticModelJoinKey(
            semantic_model_join_id=product_join.id,
            left_column_id=fact_columns["product_id"].id,
            right_column_id=product_columns["product_id"].id,
            ordinal=0,
        )
        session.add_all([*city_keys, product_key])
        dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=model.id,
            name="Sales joined dataset",
            version=1,
            status="active",
            created_by_user_id=user.id,
        )
        session.add(dataset)
        session.flush()
        field_specs = (
            (city_source, city_columns["city_name"], "city_name", "dimension"),
            (product_source, product_columns["product_name"], "product_name", "dimension"),
            (fact_source, fact_columns["amount"], "amount", "measure"),
            (fact_source, fact_columns["department"], "department", "dimension"),
        )
        fields = [
            DatasetField(
                dataset_id=dataset.id,
                model_source_id=source.id,
                source_column_id=column.id,
                name=name,
                label=name,
                field_kind="source",
                field_role=role,
                data_type=column.data_type,
                ordinal=ordinal,
            )
            for ordinal, (source, column, name, role) in enumerate(field_specs)
        ]
        session.add_all(fields)
        session.flush()
        metric = Metric(
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            code="joined_amount",
            name="Joined amount",
            version=1,
            description="Governed joined amount",
            formula={
                "op": "aggregate",
                "function": "sum",
                "field_id": str(fields[2].id),
            },
            result_type="integer",
            status="active",
            owner_user_id=user.id,
        )
        session.add(metric)
        session.flush()
        session.add(MetricDimension(metric_id=metric.id, dataset_field_id=fields[0].id))
        resources = MultiSourceResources(
            workspace_id=workspace_id,
            user_id=user.id,
            dataset_id=dataset.id,
            city_source_id=city_source.id,
            product_source_id=product_source.id,
            city_join_id=city_join.id,
            product_join_id=product_join.id,
            city_right_key_id=city_keys[0].right_column_id,
            product_id_column_id=product_columns["product_id"].id,
            city_field_id=fields[0].id,
            product_field_id=fields[1].id,
            amount_field_id=fields[2].id,
            department_field_id=fields[3].id,
            metric_id=metric.id,
            fact_batch_id=fact_batch_id,
            city_batch_id=city_batch_id,
            product_batch_id=product_batch_id,
        )
    try:
        yield session_factory, resources, engine
    finally:
        engine.dispose()


def principal(resources: MultiSourceResources) -> QueryPrincipal:
    return QueryPrincipal(
        user_id=resources.user_id,
        workspace_id=resources.workspace_id,
        permissions=frozenset({"datasets:query"}),
    )


def detail_request(resources: MultiSourceResources) -> DatasetQueryRequest:
    return DatasetQueryRequest.model_validate(
        {
            "dataset_id": resources.dataset_id,
            "selections": [
                {"field_id": resources.city_field_id, "output_name": "city"},
                {"field_id": resources.product_field_id, "output_name": "product"},
                {"field_id": resources.amount_field_id, "output_name": "amount"},
            ],
            "order_by": [{"field_id": resources.amount_field_id, "direction": "asc"}],
        }
    )


def test_multi_source_query_preserves_left_and_enforces_inner_compound_and_active(
    multi_source_store: tuple[sessionmaker[Session], MultiSourceResources, Engine],
) -> None:
    session_factory, resources, _engine = multi_source_store
    with session_factory() as session:
        result = execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )

    assert result.rows == (
        {"city": "Beijing", "product": "Widget", "amount": 10},
        {"city": None, "product": "Widget", "amount": 20},
        {"city": None, "product": "Widget", "amount": 30},
    )
    assert set(result.source_batch_ids) == {
        resources.fact_batch_id,
        resources.city_batch_id,
        resources.product_batch_id,
    }


def test_multi_source_query_executes_one_to_one_cardinality(
    multi_source_store: tuple[sessionmaker[Session], MultiSourceResources, Engine],
) -> None:
    session_factory, resources, _engine = multi_source_store
    with session_factory.begin() as session:
        product_join = session.get(SemanticModelJoin, resources.product_join_id)
        assert product_join is not None
        product_join.cardinality = "one_to_one"

    with session_factory() as session:
        result = execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )

    assert result.rows == (
        {"city": "Beijing", "product": "Widget", "amount": 10},
        {"city": None, "product": "Widget", "amount": 20},
        {"city": None, "product": "Widget", "amount": 30},
    )


def test_multi_source_metric_aggregates_after_rls_and_reports_actual_batches(
    multi_source_store: tuple[sessionmaker[Session], MultiSourceResources, Engine],
) -> None:
    session_factory, resources, _engine = multi_source_store
    with session_factory.begin() as session:
        policy = RowPolicy(
            workspace_id=resources.workspace_id,
            dataset_id=resources.dataset_id,
            name="Hide secret joined rows",
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
        session.add(policy)
        session.flush()
        session.add(RowPolicyAssignment(row_policy_id=policy.id, user_id=resources.user_id))
    request = DatasetQueryRequest.model_validate(
        {
            "dataset_id": resources.dataset_id,
            "selections": [{"field_id": resources.city_field_id, "output_name": "city"}],
            "metrics": [{"metric_id": resources.metric_id, "output_name": "total_amount"}],
            "group_by": [resources.city_field_id],
            "filter": {
                "kind": "comparison",
                "field_id": resources.amount_field_id,
                "operator": "gte",
                "value": 5,
            },
        }
    )
    with session_factory() as session:
        result = execute_dataset_query(
            session,
            principal=principal(resources),
            request=request,
        )

    assert {row["city"]: row["total_amount"] for row in result.rows} == {
        "Beijing": 10,
        None: 30,
    }
    assert result.metric_version_ids == (resources.metric_id,)
    assert set(result.source_batch_ids) == {
        resources.fact_batch_id,
        resources.city_batch_id,
        resources.product_batch_id,
    }


def test_multi_source_query_rejects_multiple_facts_and_invalid_join_keys(
    multi_source_store: tuple[sessionmaker[Session], MultiSourceResources, Engine],
) -> None:
    session_factory, resources, _engine = multi_source_store
    with session_factory.begin() as session:
        city_source = session.get(SemanticModelSource, resources.city_source_id)
        assert city_source is not None
        city_source.source_role = "fact"
    with session_factory() as session, pytest.raises(DatasetQueryValidationError) as error:
        execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )
    assert error.value.code == "semantic_model_topology_invalid"

    with session_factory.begin() as session:
        city_source = session.get(SemanticModelSource, resources.city_source_id)
        assert city_source is not None
        city_source.source_role = "dimension"
        city_key = session.scalar(
            select(SemanticModelJoinKey).where(
                SemanticModelJoinKey.semantic_model_join_id == resources.city_join_id,
                SemanticModelJoinKey.right_column_id == resources.city_right_key_id,
            )
        )
        assert city_key is not None
        city_key.right_column_id = resources.product_id_column_id
    with session_factory() as session, pytest.raises(DatasetQueryValidationError) as error:
        execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )
    assert error.value.code == "semantic_model_join_key_invalid"

    with session_factory.begin() as session:
        city_key = session.scalar(
            select(SemanticModelJoinKey).where(
                SemanticModelJoinKey.semantic_model_join_id == resources.city_join_id,
                SemanticModelJoinKey.right_column_id == resources.product_id_column_id,
            )
        )
        assert city_key is not None
        city_key.right_column_id = resources.city_right_key_id
        city_field = session.get(DatasetField, resources.city_field_id)
        assert city_field is not None
        city_field.model_source_id = resources.product_source_id
    with session_factory() as session, pytest.raises(DatasetQueryValidationError) as error:
        execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )
    assert error.value.code == "dataset_field_source_mismatch"


def test_multi_source_query_rejects_many_to_many_metadata(
    multi_source_store: tuple[sessionmaker[Session], MultiSourceResources, Engine],
) -> None:
    session_factory, resources, engine = multi_source_store
    with engine.begin() as connection:
        connection.execute(text("PRAGMA ignore_check_constraints = ON"))
        connection.execute(
            text("UPDATE semantic_model_joins SET cardinality = 'many_to_many' WHERE id = :id"),
            {"id": resources.product_join_id.hex},
        )
    with session_factory() as session, pytest.raises(DatasetQueryValidationError) as error:
        execute_dataset_query(
            session,
            principal=principal(resources),
            request=detail_request(resources),
        )
    assert error.value.code == "semantic_model_topology_invalid"
