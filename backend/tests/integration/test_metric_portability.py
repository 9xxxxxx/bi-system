import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from bi_system.db.base import Base
from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
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
from bi_system.modeling.calculated_field_contracts import CreateCalculatedField
from bi_system.modeling.contracts import DatasetQueryRequest
from bi_system.modeling.datasets import create_calculated_field_version
from bi_system.modeling.metric_contracts import CreateMetric, CreateMetricVersion
from bi_system.modeling.metrics import create_metric, create_metric_version
from bi_system.modeling.query_service import execute_dataset_query
from sqlalchemy import Boolean, Column, Date, MetaData, Numeric, String, Table, Uuid


def test_governed_queries_run_on_configured_database(tmp_path: Path) -> None:
    database_url = os.environ.get(
        "BI_DATABASE_URL",
        f"sqlite+pysqlite:///{(tmp_path / 'metric-portability.db').as_posix()}",
    )

    engine = create_database_engine(database_url)
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    batch_id = uuid4()
    dimension_batch_id = uuid4()
    table_name = f"data_{uuid4().hex}"
    dimension_table_name = f"data_{uuid4().hex}"
    table = Table(
        table_name,
        MetaData(),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_active", Boolean, nullable=False),
        Column("city", String),
        Column("amount", Numeric(38, 10)),
        Column("event_date", Date),
        Column("enabled", Boolean),
    )
    dimension_table = Table(
        dimension_table_name,
        MetaData(),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_active", Boolean, nullable=False),
        Column("city", String),
        Column("city_name", String),
    )
    try:
        table.create(engine)
        dimension_table.create(engine)
        with engine.begin() as connection:
            connection.execute(
                table.insert(),
                [
                    {
                        "_batch_id": batch_id,
                        "_active": True,
                        "city": "Beijing",
                        "amount": Decimal("10"),
                        "event_date": date(2026, 1, 2),
                        "enabled": True,
                    },
                    {
                        "_batch_id": batch_id,
                        "_active": True,
                        "city": "Beijing",
                        "amount": Decimal("20"),
                        "event_date": date(2026, 1, 1),
                        "enabled": False,
                    },
                    {
                        "_batch_id": batch_id,
                        "_active": False,
                        "city": "Beijing",
                        "amount": Decimal("999"),
                        "event_date": date(2025, 12, 31),
                        "enabled": True,
                    },
                    {
                        "_batch_id": batch_id,
                        "_active": True,
                        "city": "Shanghai",
                        "amount": Decimal("30"),
                        "event_date": date(2026, 1, 3),
                        "enabled": True,
                    },
                ],
            )
            connection.execute(
                dimension_table.insert(),
                [
                    {
                        "_batch_id": dimension_batch_id,
                        "_active": True,
                        "city": "Beijing",
                        "city_name": "Beijing",
                    },
                    {
                        "_batch_id": uuid4(),
                        "_active": False,
                        "city": "Shanghai",
                        "city_name": "Shanghai",
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
                dimension_target = ImportTarget(
                    workspace_id=workspace_id,
                    name=f"Metric dimension {uuid4().hex}",
                    physical_table_name=dimension_table_name,
                    status="active",
                )
                session.add_all([target, dimension_target])
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
                event_date_column = ImportColumn(
                    target_id=target.id,
                    source_name="Event date",
                    physical_name="event_date",
                    data_type="date",
                    nullable=True,
                    ordinal=2,
                )
                enabled_column = ImportColumn(
                    target_id=target.id,
                    source_name="Enabled",
                    physical_name="enabled",
                    data_type="boolean",
                    nullable=True,
                    ordinal=3,
                )
                dimension_city_column = ImportColumn(
                    target_id=dimension_target.id,
                    source_name="City",
                    physical_name="city",
                    data_type="string",
                    nullable=True,
                    ordinal=0,
                )
                city_name_column = ImportColumn(
                    target_id=dimension_target.id,
                    source_name="City name",
                    physical_name="city_name",
                    data_type="string",
                    nullable=True,
                    ordinal=1,
                )
                session.add_all(
                    [
                        city_column,
                        amount_column,
                        event_date_column,
                        enabled_column,
                        dimension_city_column,
                        city_name_column,
                    ]
                )
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
                dimension_source = SemanticModelSource(
                    semantic_model_id=model.id,
                    target_id=dimension_target.id,
                    alias="city",
                    source_role="dimension",
                    ordinal=1,
                )
                session.add_all([source, dimension_source])
                session.flush()
                model_join = SemanticModelJoin(
                    semantic_model_id=model.id,
                    left_source_id=source.id,
                    right_source_id=dimension_source.id,
                    join_type="left",
                    cardinality="many_to_one",
                    ordinal=0,
                )
                session.add(model_join)
                session.flush()
                session.add(
                    SemanticModelJoinKey(
                        semantic_model_join_id=model_join.id,
                        left_column_id=city_column.id,
                        right_column_id=dimension_city_column.id,
                        ordinal=0,
                    )
                )
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
                    model_source_id=dimension_source.id,
                    source_column_id=city_name_column.id,
                    name="city_name",
                    label="City name",
                    field_kind="source",
                    field_role="dimension",
                    data_type="string",
                    ordinal=1,
                )
                event_date_field = DatasetField(
                    dataset_id=dataset.id,
                    model_source_id=source.id,
                    source_column_id=event_date_column.id,
                    name="event_date",
                    label="Event date",
                    field_kind="source",
                    field_role="dimension",
                    data_type="date",
                    ordinal=2,
                )
                enabled_field = DatasetField(
                    dataset_id=dataset.id,
                    model_source_id=source.id,
                    source_column_id=enabled_column.id,
                    name="enabled",
                    label="Enabled",
                    field_kind="source",
                    field_role="dimension",
                    data_type="boolean",
                    ordinal=3,
                )
                session.add_all([amount, city, event_date_field, enabled_field])
                session.flush()
                deny_ten = RowPolicy(
                    workspace_id=workspace_id,
                    dataset_id=dataset.id,
                    name="Exclude ten",
                    version=1,
                    effect="deny",
                    expression={
                        "kind": "comparison",
                        "field_id": str(amount.id),
                        "operator": "eq",
                        "value": 10,
                    },
                    status="active",
                    created_by_user_id=owner.id,
                )
                session.add(deny_ten)
                session.flush()
                session.add(RowPolicyAssignment(row_policy_id=deny_ten.id, user_id=owner.id))
                owner_id = owner.id
                dataset_id = dataset.id
                amount_id = amount.id
                city_id = city.id
                event_date_id = event_date_field.id
                enabled_id = enabled_field.id

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

            portability_result = execute_dataset_query(
                session,
                principal=QueryPrincipal(
                    user_id=owner_id,
                    workspace_id=workspace_id,
                    permissions=frozenset({"datasets:query"}),
                ),
                request=DatasetQueryRequest.model_validate(
                    {
                        "dataset_id": dataset_id,
                        "selections": [
                            {"field_id": event_date_id, "output_name": "event_date"},
                            {"field_id": enabled_id, "output_name": "enabled"},
                            {"field_id": city_id, "output_name": "city"},
                            {"field_id": amount_id, "output_name": "amount"},
                        ],
                        "order_by": [{"field_id": event_date_id, "direction": "asc"}],
                    }
                ),
            )
            assert portability_result.rows == (
                {
                    "event_date": date(2026, 1, 1),
                    "enabled": False,
                    "city": "Beijing",
                    "amount": Decimal("20"),
                },
                {
                    "event_date": date(2026, 1, 3),
                    "enabled": True,
                    "city": None,
                    "amount": Decimal("30"),
                },
            )
            session.rollback()

            half_dataset = create_calculated_field_version(
                session,
                workspace_id=workspace_id,
                actor_user_id=owner_id,
                dataset_id=dataset_id,
                request=CreateCalculatedField.model_validate(
                    {
                        "name": "half_amount",
                        "label": "Half amount",
                        "role": "measure",
                        "data_type": "decimal",
                        "hidden": False,
                        "expression": {
                            "op": "safe_divide",
                            "numerator": {"op": "field", "field_id": amount_id},
                            "denominator": {"op": "literal", "value": 2},
                            "fallback": 0,
                        },
                    }
                ),
            )
            half_fields = {field.name: field for field in half_dataset.fields}
            band_dataset = create_calculated_field_version(
                session,
                workspace_id=workspace_id,
                actor_user_id=owner_id,
                dataset_id=half_dataset.id,
                request=CreateCalculatedField.model_validate(
                    {
                        "name": "value_band",
                        "label": "Value band",
                        "role": "dimension",
                        "data_type": "string",
                        "hidden": False,
                        "expression": {
                            "op": "case",
                            "when": {
                                "kind": "comparison",
                                "field_id": half_fields["half_amount"].id,
                                "operator": "gt",
                                "value": 10,
                            },
                            "then": {"op": "literal", "value": "high"},
                            "else": {"op": "literal", "value": "low"},
                        },
                    }
                ),
            )
            band_fields = {field.name: field for field in band_dataset.fields}

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
                "Beijing": Decimal("20"),
                None: Decimal("30"),
            }
            assert result.metric_version_ids == (created.id,)
            assert set(result.source_batch_ids) == {batch_id, dimension_batch_id}

            calculated_result = execute_dataset_query(
                session,
                principal=QueryPrincipal(
                    user_id=owner_id,
                    workspace_id=workspace_id,
                    permissions=frozenset({"datasets:query"}),
                ),
                request=DatasetQueryRequest.model_validate(
                    {
                        "dataset_id": band_dataset.id,
                        "selections": [
                            {
                                "field_id": band_fields["city_name"].id,
                                "output_name": "city",
                            },
                            {
                                "field_id": band_fields["half_amount"].id,
                                "output_name": "half_amount",
                            },
                            {
                                "field_id": band_fields["value_band"].id,
                                "output_name": "value_band",
                            },
                        ],
                        "filter": {
                            "kind": "comparison",
                            "field_id": band_fields["half_amount"].id,
                            "operator": "gte",
                            "value": 10,
                        },
                    }
                ),
            )
            assert {
                (row["city"], row["half_amount"], row["value_band"])
                for row in calculated_result.rows
            } == {
                ("Beijing", Decimal("10"), "low"),
                (None, Decimal("15"), "high"),
            }
            assert set(calculated_result.source_batch_ids) == {
                batch_id,
                dimension_batch_id,
            }
    finally:
        engine.dispose()
