import os
from uuid import uuid4

import pytest
from bi_system.db.models import Dataset, DatasetField, SemanticModel, User
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.modeling.metric_contracts import CreateMetric, CreateMetricVersion
from bi_system.modeling.metrics import create_metric, create_metric_version


def test_metric_versions_run_on_configured_database() -> None:
    database_url = os.environ.get("BI_DATABASE_URL")
    if database_url is None:
        pytest.skip("BI_DATABASE_URL is required for metric portability checks")

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    try:
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
                model = SemanticModel(
                    workspace_id=workspace_id,
                    name=f"Metric model {uuid4().hex}",
                    version=1,
                    status="active",
                    created_by_user_id=owner.id,
                )
                session.add(model)
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
                    name="amount",
                    label="Amount",
                    field_kind="calculated",
                    field_role="measure",
                    data_type="decimal",
                    expression={"op": "literal", "value": 0},
                    ordinal=0,
                )
                city = DatasetField(
                    dataset_id=dataset.id,
                    name="city",
                    label="City",
                    field_kind="calculated",
                    field_role="dimension",
                    data_type="string",
                    expression={"op": "literal", "value": ""},
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
                            "op": "aggregate",
                            "function": "sum",
                            "field_id": amount_id,
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
    finally:
        engine.dispose()
