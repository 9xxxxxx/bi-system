# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_query_principal
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.db.models import Dataset, DatasetField, Metric, SemanticModel, User
from bi_system.identity import QueryPrincipal
from bi_system.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class MetricApiContext:
    client: TestClient
    application: FastAPI
    workspace_id: UUID
    owner_user_id: UUID
    active_dataset_id: UUID
    draft_dataset_id: UUID
    foreign_dataset_id: UUID
    amount_field_id: UUID
    order_field_id: UUID
    city_field_id: UUID
    active_metric_id: UUID
    foreign_metric_id: UUID


@pytest.fixture
def metric_api_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[MetricApiContext]:
    workspace_id = uuid4()
    database_path = tmp_path / "metrics.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("BI_WORKSPACE_ID", str(workspace_id))
    clear_settings_cache()
    application = create_app()

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        session_factory = cast(sessionmaker[Session], application.state.session_factory)
        ids = _seed_metrics(session_factory, workspace_id=workspace_id)
        manager = QueryPrincipal(
            user_id=ids["owner_user_id"],
            workspace_id=workspace_id,
            permissions=frozenset({"datasets:manage"}),
        )
        application.dependency_overrides[get_query_principal] = lambda: manager
        yield MetricApiContext(
            client=client,
            application=application,
            workspace_id=workspace_id,
            **ids,
        )

    clear_settings_cache()


def _seed_metrics(
    session_factory: sessionmaker[Session],
    *,
    workspace_id: UUID,
) -> dict[str, UUID]:
    foreign_workspace_id = uuid4()
    with session_factory.begin() as session:
        owner = User(
            workspace_id=workspace_id,
            username="metric-admin",
            display_name="指标管理员",
            password_hash="not-used-in-test",
        )
        foreign_owner = User(
            workspace_id=foreign_workspace_id,
            username="foreign-admin",
            display_name="其他管理员",
            password_hash="not-used-in-test",
        )
        session.add_all([owner, foreign_owner])
        session.flush()
        semantic_model = SemanticModel(
            workspace_id=workspace_id,
            name="销售模型",
            version=1,
            status="active",
            created_by_user_id=owner.id,
        )
        foreign_model = SemanticModel(
            workspace_id=foreign_workspace_id,
            name="外部模型",
            version=1,
            status="active",
            created_by_user_id=foreign_owner.id,
        )
        session.add_all([semantic_model, foreign_model])
        session.flush()
        active_dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=semantic_model.id,
            name="销售数据集",
            version=1,
            status="active",
            created_by_user_id=owner.id,
        )
        draft_dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=semantic_model.id,
            name="销售草稿数据集",
            version=1,
            status="draft",
            created_by_user_id=owner.id,
        )
        foreign_dataset = Dataset(
            workspace_id=foreign_workspace_id,
            semantic_model_id=foreign_model.id,
            name="外部数据集",
            version=1,
            status="active",
            created_by_user_id=foreign_owner.id,
        )
        session.add_all([active_dataset, draft_dataset, foreign_dataset])
        session.flush()
        amount = DatasetField(
            dataset_id=active_dataset.id,
            name="amount",
            label="销售金额",
            field_kind="calculated",
            field_role="measure",
            data_type="decimal",
            expression={"op": "literal", "value": 0},
            ordinal=0,
        )
        order_id = DatasetField(
            dataset_id=active_dataset.id,
            name="order_id",
            label="订单编号",
            field_kind="calculated",
            field_role="dimension",
            data_type="string",
            expression={"op": "literal", "value": ""},
            ordinal=1,
        )
        city = DatasetField(
            dataset_id=active_dataset.id,
            name="city",
            label="城市",
            field_kind="calculated",
            field_role="dimension",
            data_type="string",
            expression={"op": "literal", "value": ""},
            ordinal=2,
        )
        draft_amount = DatasetField(
            dataset_id=draft_dataset.id,
            name="amount",
            label="销售金额",
            field_kind="calculated",
            field_role="measure",
            data_type="decimal",
            expression={"op": "literal", "value": 0},
            ordinal=0,
        )
        foreign_amount = DatasetField(
            dataset_id=foreign_dataset.id,
            name="amount",
            label="销售金额",
            field_kind="calculated",
            field_role="measure",
            data_type="decimal",
            expression={"op": "literal", "value": 0},
            ordinal=0,
        )
        session.add_all([amount, order_id, city, draft_amount, foreign_amount])
        session.flush()
        active_metric = Metric(
            workspace_id=workspace_id,
            dataset_id=active_dataset.id,
            code="existing_sales",
            name="已有销售额",
            version=1,
            description="已有公共口径",
            formula={"op": "aggregate", "function": "sum", "field_id": str(amount.id)},
            result_type="decimal",
            status="active",
            owner_user_id=owner.id,
        )
        foreign_metric = Metric(
            workspace_id=foreign_workspace_id,
            dataset_id=foreign_dataset.id,
            code="foreign_sales",
            name="外部销售额",
            version=1,
            description="其他工作区口径",
            formula={
                "op": "aggregate",
                "function": "sum",
                "field_id": str(foreign_amount.id),
            },
            result_type="decimal",
            status="active",
            owner_user_id=foreign_owner.id,
        )
        session.add_all([active_metric, foreign_metric])
        session.flush()
    return {
        "owner_user_id": owner.id,
        "active_dataset_id": active_dataset.id,
        "draft_dataset_id": draft_dataset.id,
        "foreign_dataset_id": foreign_dataset.id,
        "amount_field_id": amount.id,
        "order_field_id": order_id.id,
        "city_field_id": city.id,
        "active_metric_id": active_metric.id,
        "foreign_metric_id": foreign_metric.id,
    }


def _metric_payload(context: MetricApiContext) -> dict[str, object]:
    return {
        "dataset_id": str(context.active_dataset_id),
        "code": "average_order_value",
        "name": "平均订单金额",
        "description": "销售金额除以去重订单数",
        "formula": {
            "op": "safe_divide",
            "numerator": {
                "op": "aggregate",
                "function": "sum",
                "field_id": str(context.amount_field_id),
            },
            "denominator": {
                "op": "aggregate",
                "function": "count_distinct",
                "field_id": str(context.order_field_id),
            },
            "fallback": 0,
        },
        "unit": "元/单",
        "dimension_field_ids": [str(context.city_field_id)],
        "status": "active",
    }


def test_metric_api_creates_lists_and_reads_metric(metric_api_context: MetricApiContext) -> None:
    created = cast(
        Response,
        metric_api_context.client.post("/api/v1/metrics", json=_metric_payload(metric_api_context)),
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["series_id"]
    assert payload["version"] == 1
    assert payload["result_type"] == "decimal"
    assert payload["dimension_field_ids"] == [str(metric_api_context.city_field_id)]
    assert payload["formula"]["op"] == "safe_divide"

    listed = cast(Response, metric_api_context.client.get("/api/v1/metrics?offset=0&limit=10"))
    stored = cast(Response, metric_api_context.client.get(f"/api/v1/metrics/{payload['id']}"))
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert {item["id"] for item in listed.json()["items"]} == {
        str(metric_api_context.active_metric_id),
        payload["id"],
    }
    assert stored.status_code == 200
    assert {key: value for key, value in stored.json().items() if key != "updated_at"} == {
        key: value for key, value in payload.items() if key != "updated_at"
    }


def test_metric_versions_are_immutable_and_keep_series(
    metric_api_context: MetricApiContext,
) -> None:
    original = cast(
        Response,
        metric_api_context.client.get(f"/api/v1/metrics/{metric_api_context.active_metric_id}"),
    ).json()
    version = cast(
        Response,
        metric_api_context.client.post(
            f"/api/v1/metrics/{metric_api_context.active_metric_id}/versions",
            json={"name": "已有销售额(新口径)", "status": "draft", "unit": None},
        ),
    )

    assert version.status_code == 201
    assert version.json()["version"] == 2
    assert version.json()["series_id"] == original["series_id"]
    assert version.json()["name"] == "已有销售额(新口径)"
    assert version.json()["unit"] is None
    unchanged = cast(
        Response,
        metric_api_context.client.get(f"/api/v1/metrics/{metric_api_context.active_metric_id}"),
    )
    assert unchanged.json() == original


def test_metric_api_enforces_workspace_dataset_and_field_ownership(
    metric_api_context: MetricApiContext,
) -> None:
    foreign = _metric_payload(metric_api_context)
    foreign["dataset_id"] = str(metric_api_context.foreign_dataset_id)
    foreign_response = cast(
        Response,
        metric_api_context.client.post("/api/v1/metrics", json=foreign),
    )
    wrong_field = _metric_payload(metric_api_context)
    formula = cast(dict[str, object], wrong_field["formula"])
    numerator = cast(dict[str, object], formula["numerator"])
    numerator["field_id"] = str(uuid4())
    wrong_field_response = cast(
        Response,
        metric_api_context.client.post("/api/v1/metrics", json=wrong_field),
    )
    hidden = cast(
        Response,
        metric_api_context.client.get(f"/api/v1/metrics/{metric_api_context.foreign_metric_id}"),
    )

    assert foreign_response.status_code == 404
    assert foreign_response.json()["detail"]["code"] == "metric_resource_not_found"
    assert wrong_field_response.status_code == 422
    assert wrong_field_response.json()["detail"]["code"] == "invalid_metric_configuration"
    assert hidden.status_code == 404


def test_active_metric_requires_active_dataset(metric_api_context: MetricApiContext) -> None:
    payload = _metric_payload(metric_api_context)
    payload["dataset_id"] = str(metric_api_context.draft_dataset_id)
    formula = cast(dict[str, object], payload["formula"])
    numerator = cast(dict[str, object], formula["numerator"])
    denominator = cast(dict[str, object], formula["denominator"])
    session_factory = cast(
        sessionmaker[Session], metric_api_context.application.state.session_factory
    )
    with session_factory() as session:
        draft_fields = session.scalars(
            select(DatasetField).where(
                DatasetField.dataset_id == metric_api_context.draft_dataset_id
            )
        ).all()
        numerator["field_id"] = str(draft_fields[0].id)
        denominator["field_id"] = str(draft_fields[0].id)
        payload["dimension_field_ids"] = []

    active = cast(Response, metric_api_context.client.post("/api/v1/metrics", json=payload))
    payload["status"] = "draft"
    draft = cast(Response, metric_api_context.client.post("/api/v1/metrics", json=payload))

    assert active.status_code == 404
    assert draft.status_code == 201


def test_metric_api_rejects_invalid_aggregate_dimension_and_duplicate_code(
    metric_api_context: MetricApiContext,
) -> None:
    invalid_dimension = _metric_payload(metric_api_context)
    invalid_dimension["dimension_field_ids"] = [str(metric_api_context.amount_field_id)]
    response = cast(
        Response,
        metric_api_context.client.post("/api/v1/metrics", json=invalid_dimension),
    )
    assert response.status_code == 422
    assert "dimension fields" in response.json()["detail"]["message"]

    invalid_aggregate = _metric_payload(metric_api_context)
    invalid_formula = cast(dict[str, object], invalid_aggregate["formula"])
    invalid_numerator = cast(dict[str, object], invalid_formula["numerator"])
    invalid_numerator["field_id"] = str(metric_api_context.city_field_id)
    response = cast(
        Response,
        metric_api_context.client.post("/api/v1/metrics", json=invalid_aggregate),
    )
    assert response.status_code == 422
    assert "numeric field" in response.json()["detail"]["message"]

    duplicate = _metric_payload(metric_api_context)
    duplicate["code"] = "existing_sales"
    conflict = cast(Response, metric_api_context.client.post("/api/v1/metrics", json=duplicate))
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "metric_version_conflict"


def test_metric_write_requires_dataset_manage_permission(
    metric_api_context: MetricApiContext,
) -> None:
    viewer = QueryPrincipal(
        user_id=metric_api_context.owner_user_id,
        workspace_id=metric_api_context.workspace_id,
    )
    metric_api_context.application.dependency_overrides[get_query_principal] = lambda: viewer

    response = cast(
        Response,
        metric_api_context.client.post("/api/v1/metrics", json=_metric_payload(metric_api_context)),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "metric_manage_forbidden"
