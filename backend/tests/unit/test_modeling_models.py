from pathlib import Path
from uuid import uuid4

import pytest
from bi_system.db.base import Base
from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    Metric,
    MetricDimension,
    Role,
    RowPolicy,
    RowPolicyAssignment,
    SemanticModel,
    SemanticModelJoin,
    SemanticModelJoinKey,
    SemanticModelSource,
    User,
    UserRole,
)
from bi_system.db.session import create_database_engine, create_session_factory
from sqlalchemy.exc import IntegrityError

EXPECTED_MODELING_TABLES = {
    "dataset_fields",
    "datasets",
    "metric_dimensions",
    "metrics",
    "roles",
    "row_policies",
    "row_policy_assignments",
    "semantic_model_joins",
    "semantic_model_join_keys",
    "semantic_model_sources",
    "semantic_models",
    "user_roles",
    "users",
}


def test_modeling_metadata_contains_expected_tables() -> None:
    assert EXPECTED_MODELING_TABLES.issubset(Base.metadata.tables)


def test_identity_and_modeling_models_round_trip_on_sqlite(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'models.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()

    try:
        with session_factory.begin() as session:
            user = User(
                workspace_id=workspace_id,
                username="data.admin",
                display_name="Data Admin",
                password_hash="hashed-password",
            )
            role = Role(
                workspace_id=workspace_id,
                code="data_admin",
                name="Data administrator",
                permissions=["datasets:manage", "datasets:query"],
            )
            session.add_all([user, role])
            session.flush()
            session.add(UserRole(user_id=user.id, role_id=role.id))

            fact_target = ImportTarget(
                workspace_id=workspace_id,
                name="Sales fact",
                physical_table_name=f"data_{uuid4().hex}",
                status="active",
            )
            dimension_target = ImportTarget(
                workspace_id=workspace_id,
                name="City dimension",
                physical_table_name=f"data_{uuid4().hex}",
                status="active",
            )
            session.add_all([fact_target, dimension_target])
            session.flush()

            fact_city = ImportColumn(
                target_id=fact_target.id,
                source_name="City ID",
                physical_name="city_id",
                data_type="string",
                nullable=False,
                ordinal=0,
            )
            dimension_city = ImportColumn(
                target_id=dimension_target.id,
                source_name="City ID",
                physical_name="city_id",
                data_type="string",
                nullable=False,
                ordinal=0,
            )
            session.add_all([fact_city, dimension_city])
            session.flush()

            semantic_model = SemanticModel(
                workspace_id=workspace_id,
                name="Sales model",
                version=1,
                status="active",
                created_by_user_id=user.id,
            )
            session.add(semantic_model)
            session.flush()
            fact_source = SemanticModelSource(
                semantic_model_id=semantic_model.id,
                target_id=fact_target.id,
                alias="sales",
                source_role="fact",
                ordinal=0,
            )
            dimension_source = SemanticModelSource(
                semantic_model_id=semantic_model.id,
                target_id=dimension_target.id,
                alias="city",
                source_role="dimension",
                ordinal=1,
            )
            session.add_all([fact_source, dimension_source])
            session.flush()
            model_join = SemanticModelJoin(
                semantic_model_id=semantic_model.id,
                left_source_id=fact_source.id,
                right_source_id=dimension_source.id,
                join_type="left",
                cardinality="many_to_one",
                risk_acknowledged=True,
                ordinal=0,
            )
            session.add(model_join)
            session.flush()
            session.add(
                SemanticModelJoinKey(
                    semantic_model_join_id=model_join.id,
                    left_column_id=fact_city.id,
                    right_column_id=dimension_city.id,
                    ordinal=0,
                ),
            )

            dataset = Dataset(
                workspace_id=workspace_id,
                semantic_model_id=semantic_model.id,
                name="Sales dataset",
                version=1,
                status="active",
                created_by_user_id=user.id,
            )
            session.add(dataset)
            session.flush()
            city_field = DatasetField(
                dataset_id=dataset.id,
                model_source_id=dimension_source.id,
                source_column_id=dimension_city.id,
                name="city_id",
                label="City",
                field_kind="source",
                field_role="dimension",
                data_type="string",
                ordinal=0,
            )
            session.add(city_field)
            session.flush()

            metric = Metric(
                workspace_id=workspace_id,
                dataset_id=dataset.id,
                code="order_count",
                name="Order count",
                version=1,
                description="Number of sales rows",
                formula={"op": "count"},
                result_type="integer",
                unit="orders",
                status="active",
                owner_user_id=user.id,
            )
            policy = RowPolicy(
                workspace_id=workspace_id,
                dataset_id=dataset.id,
                name="Assigned cities",
                version=1,
                effect="allow",
                expression={"op": "in", "field_id": str(city_field.id), "values": ["001"]},
                status="active",
                created_by_user_id=user.id,
            )
            session.add_all([metric, policy])
            session.flush()
            session.add_all(
                [
                    MetricDimension(metric_id=metric.id, dataset_field_id=city_field.id),
                    RowPolicyAssignment(row_policy_id=policy.id, role_id=role.id),
                ],
            )
            dataset_id = dataset.id
            metric_id = metric.id

        with session_factory() as session:
            stored_dataset = session.get(Dataset, dataset_id)
            stored_metric = session.get(Metric, metric_id)
            assert stored_dataset is not None
            assert stored_dataset.semantic_model_id == semantic_model.id
            assert stored_dataset.series_id is not None
            assert stored_metric is not None
            assert stored_metric.formula == {"op": "count"}
            assert role.permissions == ["datasets:manage", "datasets:query"]
    finally:
        engine.dispose()


def test_row_policy_assignment_requires_exactly_one_principal(tmp_path: Path) -> None:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'constraints.db').as_posix()}"
    )
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            session.add(RowPolicyAssignment(row_policy_id=uuid4()))
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()
