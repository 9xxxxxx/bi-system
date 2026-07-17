import os
from decimal import Decimal
from uuid import uuid4

import pytest
from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    SemanticModel,
    SemanticModelSource,
    User,
)
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from bi_system.modeling.contracts import DatasetQueryRequest
from bi_system.modeling.metric_contracts import CreateMetric, CreateMetricVersion
from bi_system.modeling.metrics import create_metric, create_metric_version
from bi_system.modeling.query_service import execute_dataset_query
from sqlalchemy import Boolean, Column, MetaData, Numeric, String, Table, Uuid


def test_metric_versions_run_on_configured_database() -> None:
    database_url = os.environ.get("BI_DATABASE_URL")
    if database_url is None:
        pytest.skip("BI_DATABASE_URL is required for metric portability checks")

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    batch_id = uuid4()
    table_name = f"data_{uuid4().hex}"
    table = Table(
        table_name,
        MetaData(),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_active", Boolean, nullable=False),
        Column("city", String),
        Column("amount", Numeric(38, 10)),
    )
    try:
        table.create(engine)
        with engine.begin() as connection:
            connection.execute(
                table.insert(),
                [
                    {
                        "_batch_id": batch_id,
                        "_active": True,
                        "city": "Beijing",
                        "amount": Decimal("10"),
                    },
                    {
                        "_batch_id": batch_id,
                        "_active": True,
                        "city": "Beijing",
                        "amount": Decimal("20"),
                    },
                    {
                        "_batch_id": batch_id,
                        "_active": False,
                        "city": "Beijing",
                        "amount": Decimal("999"),
                    },
                    {
                        "_batch_id": batch_id,
                        "_active": True,
                        "city": "Shanghai",
                        "amount": Decimal("30"),
                    },
                ],
            )
        with session_factory() as session:
            with session.begin():
                owner = User(
                    workspace_id=workspace_id,
                    username=f"metric-{uuid4().hex}",
                    display_name="Metric portability owner",
                    password_hash="not-used-in-test",
                )
                session.add(owner)
                session.flush()
                target = ImportTarget(
                    workspace_id=workspace_id,
                    name=f"Metric target {uuid4().hex}",
                    physical_table_name=table_name,
                    status="active",
                )
                session.add(target)
                session.flush()
                city_column = ImportColumn(
                    target_id=target.id,
                    source_name="City",
                    physical_name="city",
                    data_type="string",
                    nullable=True,
                    ordinal=0,
                )
                amount_column = ImportColumn(
                    target_id=target.id,
                    source_name="Amount",
                    physical_name="amount",
                    data_type="decimal",
                    nullable=True,
                    ordinal=1,
                )
                session.add_all([city_column, amount_column])
                session.flush()
                model = SemanticModel(
                    workspace_id=workspace_id,
                    name=f"Metric model {uuid4().hex}",
                    version=1,
                    status="active",
                    created_by_user_id=owner.id,
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
                    name=f"Metric dataset {uuid4().hex}",
                    version=1,
                    status="active",
                    created_by_user_id=owner.id,
                )
                session.add(dataset)
                session.flush()
                amount = DatasetField(
                    dataset_id=dataset.id,
                    model_source_id=source.id,
                    source_column_id=amount_column.id,
                    name="amount",
                    label="Amount",
                    field_kind="source",
                    field_role="measure",
                    data_type="decimal",
                    ordinal=0,
                )
                city = DatasetField(
                    dataset_id=dataset.id,
                    model_source_id=source.id,
                    source_column_id=city_column.id,
                    name="city",
                    label="City",
                    field_kind="source",
                    field_role="dimension",
                    data_type="string",
                    ordinal=1,
                )
                session.add_all([amount, city])
                session.flush()
                owner_id = owner.id
                dataset_id = dataset.id
                amount_id = amount.id
                city_id = city.id

            created = create_metric(
                session,
                workspace_id=workspace_id,
                actor_user_id=owner_id,
                request=CreateMetric.model_validate(
                    {
                        "dataset_id": dataset_id,
                        "code": f"portable_{uuid4().hex}",
                        "name": "Portable metric",
                        "description": "Metric persistence portability check",
                        "formula": {
                            "op": "safe_divide",
                            "numerator": {
                                "op": "aggregate",
                                "function": "sum",
                                "field_id": amount_id,
                            },
                            "denominator": {
                                "op": "aggregate",
                                "function": "count",
                                "field_id": amount_id,
                            },
                            "fallback": 0,
                        },
                        "dimension_field_ids": [city_id],
                        "status": "active",
                    }
                ),
            )
            version = create_metric_version(
                session,
                workspace_id=workspace_id,
                actor_user_id=owner_id,
                metric_id=created.id,
                request=CreateMetricVersion(name="Portable metric v2"),
            )

            assert created.version == 1
            assert version.version == 2
            assert version.series_id == created.series_id
            assert version.formula == created.formula
            assert version.dimension_field_ids == [city_id]

            result = execute_dataset_query(
                session,
                principal=QueryPrincipal(
                    user_id=owner_id,
                    workspace_id=workspace_id,
                    permissions=frozenset({"datasets:query"}),
                ),
                request=DatasetQueryRequest.model_validate(
                    {
                        "dataset_id": dataset_id,
                        "selections": [{"field_id": city_id, "output_name": "city"}],
                        "metrics": [
                            {
                                "metric_id": created.id,
                                "output_name": "average_amount",
                            }
                        ],
                        "group_by": [city_id],
                    }
                ),
            )
            rows_by_city = {row["city"]: row["average_amount"] for row in result.rows}
            assert rows_by_city == {
                "Beijing": Decimal("15"),
                "Shanghai": Decimal("30"),
            }
            assert result.metric_version_ids == (created.id,)
            assert result.source_batch_ids == (batch_id,)
    finally:
        engine.dispose()
