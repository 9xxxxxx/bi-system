# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_query_principal
from bi_system.api.routes.datasets import router as datasets_router
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    Metric,
    SemanticModel,
    SemanticModelSource,
    User,
)
from bi_system.identity import QueryPrincipal
from bi_system.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class DatasetApiContext:
    client: TestClient
    application: FastAPI
    workspace_id: UUID
    owner_user_id: UUID
    semantic_model_id: UUID
    inactive_semantic_model_id: UUID
    foreign_semantic_model_id: UUID
    model_source_id: UUID
    source_column_id: UUID
    active_dataset_id: UUID
    draft_dataset_id: UUID
    deleted_dataset_id: UUID
    foreign_dataset_id: UUID


@pytest.fixture
def dataset_api_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[DatasetApiContext]:
    workspace_id = uuid4()
    database_path = tmp_path / "datasets.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("BI_WORKSPACE_ID", str(workspace_id))
    clear_settings_cache()
    application = create_app()
    application.include_router(datasets_router, prefix="/api/v1/datasets")

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        session_factory = cast(sessionmaker[Session], application.state.session_factory)
        ids = _seed_datasets(session_factory, workspace_id=workspace_id)
        manager = QueryPrincipal(
            user_id=ids["owner_user_id"],
            workspace_id=workspace_id,
            permissions=frozenset({"datasets:manage"}),
        )
        application.dependency_overrides[get_query_principal] = lambda: manager
        yield DatasetApiContext(
            client=client,
            application=application,
            workspace_id=workspace_id,
            **ids,
        )

    clear_settings_cache()


def _seed_datasets(
    session_factory: sessionmaker[Session],
    *,
    workspace_id: UUID,
) -> dict[str, UUID]:
    foreign_workspace_id = uuid4()
    now = datetime.now(UTC)
    with session_factory.begin() as session:
        owner = User(
            workspace_id=workspace_id,
            username="data-admin",
            display_name="数据管理员",
            password_hash="not-used-in-test",
        )
        foreign_owner = User(
            workspace_id=foreign_workspace_id,
            username="foreign-admin",
            display_name="其他工作区管理员",
            password_hash="not-used-in-test",
        )
        session.add_all([owner, foreign_owner])
        session.flush()

        active_model = SemanticModel(
            workspace_id=workspace_id,
            name="销售模型",
            version=1,
            status="active",
            created_by_user_id=owner.id,
        )
        draft_model = SemanticModel(
            workspace_id=workspace_id,
            name="库存模型",
            version=1,
            status="draft",
            created_by_user_id=owner.id,
        )
        deleted_model = SemanticModel(
            workspace_id=workspace_id,
            name="删除模型",
            version=1,
            status="deleted",
            created_by_user_id=owner.id,
            deleted_at=now,
        )
        foreign_model = SemanticModel(
            workspace_id=foreign_workspace_id,
            name="其他工作区模型",
            version=1,
            status="active",
            created_by_user_id=foreign_owner.id,
        )
        session.add_all([active_model, draft_model, deleted_model, foreign_model])
        session.flush()

        target = ImportTarget(
            workspace_id=workspace_id,
            name="销售明细",
            physical_table_name=f"data_{uuid4().hex}",
            status="active",
        )
        session.add(target)
        session.flush()
        source_column = ImportColumn(
            target_id=target.id,
            source_name="销售金额",
            physical_name="amount",
            data_type="decimal",
            nullable=False,
            ordinal=0,
        )
        session.add(source_column)
        model_source = SemanticModelSource(
            semantic_model_id=active_model.id,
            target_id=target.id,
            alias="sales",
            source_role="fact",
            ordinal=0,
        )
        session.add(model_source)
        session.flush()

        active_dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=active_model.id,
            name="销售经营数据集",
            version=1,
            description="统一销售分析口径",
            status="active",
            created_by_user_id=owner.id,
            updated_at=now,
        )
        draft_dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=draft_model.id,
            name="库存数据集",
            version=1,
            status="draft",
            created_by_user_id=owner.id,
            updated_at=now - timedelta(days=1),
        )
        deleted_dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=deleted_model.id,
            name="已删除数据集",
            version=1,
            status="deleted",
            created_by_user_id=owner.id,
            updated_at=now + timedelta(days=1),
            deleted_at=now,
        )
        foreign_dataset = Dataset(
            workspace_id=foreign_workspace_id,
            semantic_model_id=foreign_model.id,
            name="其他工作区数据集",
            version=1,
            status="active",
            created_by_user_id=foreign_owner.id,
            updated_at=now + timedelta(days=2),
        )
        session.add_all([active_dataset, draft_dataset, deleted_dataset, foreign_dataset])
        session.flush()

        session.add(
            DatasetField(
                dataset_id=active_dataset.id,
                model_source_id=model_source.id,
                name="amount",
                label="销售金额",
                field_kind="calculated",
                field_role="measure",
                data_type="decimal",
                expression={"op": "literal", "value": 0},
                ordinal=0,
            )
        )
        session.add_all(
            [
                Metric(
                    workspace_id=workspace_id,
                    dataset_id=active_dataset.id,
                    code="sales_amount",
                    name="销售金额",
                    version=1,
                    description="销售金额汇总",
                    formula={"op": "sum", "field": "amount"},
                    result_type="decimal",
                    status="active",
                    owner_user_id=owner.id,
                ),
                Metric(
                    workspace_id=workspace_id,
                    dataset_id=active_dataset.id,
                    code="old_sales_amount",
                    name="旧销售金额",
                    version=1,
                    description="已删除指标",
                    formula={"op": "sum", "field": "amount"},
                    result_type="decimal",
                    status="deleted",
                    owner_user_id=owner.id,
                    deleted_at=now,
                ),
            ]
        )

    return {
        "owner_user_id": owner.id,
        "semantic_model_id": active_model.id,
        "inactive_semantic_model_id": deleted_model.id,
        "foreign_semantic_model_id": foreign_model.id,
        "model_source_id": model_source.id,
        "source_column_id": source_column.id,
        "active_dataset_id": active_dataset.id,
        "draft_dataset_id": draft_dataset.id,
        "deleted_dataset_id": deleted_dataset.id,
        "foreign_dataset_id": foreign_dataset.id,
    }


def test_dataset_list_is_stable_paginated_and_summarized(
    dataset_api_context: DatasetApiContext,
) -> None:
    first = cast(
        Response,
        dataset_api_context.client.get("/api/v1/datasets?offset=0&limit=1"),
    )
    second = cast(
        Response,
        dataset_api_context.client.get("/api/v1/datasets?offset=1&limit=1"),
    )

    assert first.status_code == 200
    assert first.json()["total"] == 2
    assert first.json()["offset"] == 0
    assert first.json()["limit"] == 1
    assert first.json()["items"] == [
        {
            "id": str(dataset_api_context.active_dataset_id),
            "name": "销售经营数据集",
            "description": "统一销售分析口径",
            "status": "active",
            "source_count": 1,
            "field_count": 1,
            "metric_count": 1,
            "owner_name": "数据管理员",
            "updated_at": first.json()["items"][0]["updated_at"],
        }
    ]
    assert second.status_code == 200
    assert second.json()["total"] == 2
    assert second.json()["items"][0]["id"] == str(dataset_api_context.draft_dataset_id)


def test_dataset_summary_can_be_read_by_id(
    dataset_api_context: DatasetApiContext,
) -> None:
    response = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_api_context.active_dataset_id}"),
    )

    assert response.status_code == 200
    assert response.json()["source_count"] == 1
    assert response.json()["field_count"] == 1
    assert response.json()["metric_count"] == 1
    assert response.json()["owner_name"] == "数据管理员"


@pytest.mark.parametrize("resource", ["deleted_dataset_id", "foreign_dataset_id"])
def test_dataset_api_hides_deleted_and_cross_workspace_resources(
    dataset_api_context: DatasetApiContext,
    resource: str,
) -> None:
    dataset_id = cast(UUID, getattr(dataset_api_context, resource))
    response = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_id}"),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "dataset_not_found"


def test_dataset_list_validates_pagination(
    dataset_api_context: DatasetApiContext,
) -> None:
    negative_offset = cast(
        Response,
        dataset_api_context.client.get("/api/v1/datasets?offset=-1"),
    )
    excessive_limit = cast(
        Response,
        dataset_api_context.client.get("/api/v1/datasets?limit=101"),
    )

    assert negative_offset.status_code == 422
    assert excessive_limit.status_code == 422


def _create_dataset_payload(context: DatasetApiContext) -> dict[str, object]:
    return {
        "semantic_model_id": str(context.semantic_model_id),
        "name": "销售目标数据集",
        "description": "销售目标分析口径",
        "fields": [
            {
                "model_source_id": str(context.model_source_id),
                "source_column_id": str(context.source_column_id),
                "name": "sales_amount",
                "label": "销售金额",
                "role": "measure",
                "hidden": False,
            }
        ],
    }


def test_dataset_api_creates_draft_and_returns_fields(
    dataset_api_context: DatasetApiContext,
) -> None:
    created = cast(
        Response,
        dataset_api_context.client.post(
            "/api/v1/datasets",
            json=_create_dataset_payload(dataset_api_context),
        ),
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "draft"
    assert payload["version"] == 1
    assert payload["semantic_model_id"] == str(dataset_api_context.semantic_model_id)
    assert payload["field_count"] == 1
    assert payload["fields"] == [
        {
            "id": payload["fields"][0]["id"],
            "model_source_id": str(dataset_api_context.model_source_id),
            "source_column_id": str(dataset_api_context.source_column_id),
            "name": "sales_amount",
            "label": "销售金额",
            "field_kind": "source",
            "role": "measure",
            "data_type": "decimal",
            "hidden": False,
            "ordinal": 0,
        }
    ]

    stored = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{payload['id']}"),
    )
    assert stored.status_code == 200
    assert stored.json()["fields"] == payload["fields"]

    duplicate = cast(
        Response,
        dataset_api_context.client.post(
            "/api/v1/datasets",
            json=_create_dataset_payload(dataset_api_context),
        ),
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"]["code"] == "invalid_dataset_configuration"


def test_dataset_api_versions_copy_then_replace_fields(
    dataset_api_context: DatasetApiContext,
) -> None:
    original = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_api_context.active_dataset_id}"),
    ).json()
    copied = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.active_dataset_id}/versions",
            json={},
        ),
    )
    replaced = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.active_dataset_id}/versions",
            json={"fields": _create_dataset_payload(dataset_api_context)["fields"]},
        ),
    )

    assert copied.status_code == 201
    assert copied.json()["version"] == 2
    assert copied.json()["series_id"] == original["series_id"]
    assert copied.json()["fields"][0]["field_kind"] == "calculated"
    assert replaced.status_code == 201
    assert replaced.json()["version"] == 3
    assert replaced.json()["fields"][0]["field_kind"] == "source"
    assert replaced.json()["fields"][0]["data_type"] == "decimal"

    unchanged = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_api_context.active_dataset_id}"),
    )
    assert unchanged.json()["version"] == 1
    assert unchanged.json()["fields"][0]["field_kind"] == "calculated"


def test_dataset_api_activation_archives_previous_active_version(
    dataset_api_context: DatasetApiContext,
) -> None:
    version = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.active_dataset_id}/versions",
            json={"fields": _create_dataset_payload(dataset_api_context)["fields"]},
        ),
    )

    activated = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{version.json()['id']}/activate",
        ),
    )
    previous = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_api_context.active_dataset_id}"),
    )

    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert activated.json()["version"] == 2
    assert previous.status_code == 200
    assert previous.json()["status"] == "archived"


def test_dataset_api_activation_requires_active_model_and_fields(
    dataset_api_context: DatasetApiContext,
) -> None:
    response = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.draft_dataset_id}/activate"
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dataset_activation_conflict"


def test_dataset_api_rejects_foreign_models_and_invalid_field_ownership(
    dataset_api_context: DatasetApiContext,
) -> None:
    foreign_model_payload = _create_dataset_payload(dataset_api_context)
    foreign_model_payload["semantic_model_id"] = str(dataset_api_context.foreign_semantic_model_id)
    foreign_model = cast(
        Response,
        dataset_api_context.client.post(
            "/api/v1/datasets",
            json=foreign_model_payload,
        ),
    )

    inactive_model_payload = _create_dataset_payload(dataset_api_context)
    inactive_model_payload["semantic_model_id"] = str(
        dataset_api_context.inactive_semantic_model_id
    )
    inactive_model = cast(
        Response,
        dataset_api_context.client.post(
            "/api/v1/datasets",
            json=inactive_model_payload,
        ),
    )

    invalid_field_payload = _create_dataset_payload(dataset_api_context)
    invalid_fields = cast(list[dict[str, object]], invalid_field_payload["fields"])
    invalid_fields[0]["source_column_id"] = str(uuid4())
    invalid_field = cast(
        Response,
        dataset_api_context.client.post(
            "/api/v1/datasets",
            json=invalid_field_payload,
        ),
    )

    assert foreign_model.status_code == 404
    assert foreign_model.json()["detail"]["code"] == "dataset_resource_not_found"
    assert inactive_model.status_code == 404
    assert inactive_model.json()["detail"]["code"] == "dataset_resource_not_found"
    assert invalid_field.status_code == 422
    assert invalid_field.json()["detail"]["code"] == "invalid_dataset_configuration"


def test_dataset_write_requires_manage_permission(
    dataset_api_context: DatasetApiContext,
) -> None:
    viewer = QueryPrincipal(
        user_id=dataset_api_context.owner_user_id,
        workspace_id=dataset_api_context.workspace_id,
    )
    dataset_api_context.application.dependency_overrides[get_query_principal] = lambda: viewer

    response = cast(
        Response,
        dataset_api_context.client.post(
            "/api/v1/datasets",
            json=_create_dataset_payload(dataset_api_context),
        ),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "dataset_manage_forbidden"


def _calculated_field_payload(field_id: str) -> dict[str, object]:
    return {
        "name": "half_amount",
        "label": "Half amount",
        "role": "measure",
        "data_type": "decimal",
        "hidden": False,
        "expression": {
            "op": "safe_divide",
            "numerator": {"op": "field", "field_id": field_id},
            "denominator": {"op": "literal", "value": 2},
            "fallback": 0,
        },
    }


def test_calculated_field_api_creates_vnext_and_rewrites_all_version_dependencies(
    dataset_api_context: DatasetApiContext,
) -> None:
    original = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_api_context.active_dataset_id}"),
    ).json()
    original_field_id = original["fields"][0]["id"]
    created = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.active_dataset_id}/calculated-fields",
            json=_calculated_field_payload(original_field_id),
        ),
    )

    assert created.status_code == 201
    assert created.json()["version"] == 2
    assert created.json()["series_id"] == original["series_id"]
    assert created.json()["field_count"] == 2
    copied_field_id = created.json()["fields"][0]["id"]
    calculated_field_id = created.json()["fields"][1]["id"]
    assert copied_field_id != original_field_id

    copied_again = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{created.json()['id']}/versions",
            json={},
        ),
    )
    assert copied_again.status_code == 201
    assert copied_again.json()["version"] == 3

    session_factory = cast(
        sessionmaker[Session], dataset_api_context.application.state.session_factory
    )
    with session_factory() as session:
        calculated = session.get(DatasetField, UUID(calculated_field_id))
        copied_v3_fields = session.scalars(
            select(DatasetField)
            .where(DatasetField.dataset_id == UUID(copied_again.json()["id"]))
            .order_by(DatasetField.ordinal)
        ).all()
        assert calculated is not None
        assert calculated.expression is not None
        assert calculated.expression["numerator"]["field_id"] == copied_field_id
        assert copied_v3_fields[0].id != UUID(copied_field_id)
        assert copied_v3_fields[1].expression is not None
        assert copied_v3_fields[1].expression["numerator"]["field_id"] == str(
            copied_v3_fields[0].id
        )

    unchanged = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_api_context.active_dataset_id}"),
    )
    assert unchanged.json() == original


def test_calculated_field_api_rejects_cross_dataset_type_errors_and_cycles(
    dataset_api_context: DatasetApiContext,
) -> None:
    original = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_api_context.active_dataset_id}"),
    ).json()
    field_id = original["fields"][0]["id"]
    cross_dataset = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.active_dataset_id}/calculated-fields",
            json=_calculated_field_payload(str(uuid4())),
        ),
    )
    invalid_type_payload = _calculated_field_payload(field_id)
    invalid_type_payload["data_type"] = "string"
    invalid_type_payload["role"] = "dimension"
    invalid_type = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.active_dataset_id}/calculated-fields",
            json=invalid_type_payload,
        ),
    )

    assert cross_dataset.status_code == 422
    assert cross_dataset.json()["detail"]["code"] == "invalid_calculated_field"
    assert invalid_type.status_code == 422

    session_factory = cast(
        sessionmaker[Session], dataset_api_context.application.state.session_factory
    )
    with session_factory.begin() as session:
        field = session.get(DatasetField, UUID(field_id))
        assert field is not None
        field.expression = {"op": "field", "field_id": field_id}
    cyclic = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.active_dataset_id}/calculated-fields",
            json=_calculated_field_payload(field_id),
        ),
    )
    assert cyclic.status_code == 422
    assert "cycle" in cyclic.json()["detail"]["message"]


def test_calculated_field_write_requires_manage_permission(
    dataset_api_context: DatasetApiContext,
) -> None:
    original = cast(
        Response,
        dataset_api_context.client.get(f"/api/v1/datasets/{dataset_api_context.active_dataset_id}"),
    ).json()
    viewer = QueryPrincipal(
        user_id=dataset_api_context.owner_user_id,
        workspace_id=dataset_api_context.workspace_id,
    )
    dataset_api_context.application.dependency_overrides[get_query_principal] = lambda: viewer

    response = cast(
        Response,
        dataset_api_context.client.post(
            f"/api/v1/datasets/{dataset_api_context.active_dataset_id}/calculated-fields",
            json=_calculated_field_payload(original["fields"][0]["id"]),
        ),
    )
    assert response.status_code == 403
