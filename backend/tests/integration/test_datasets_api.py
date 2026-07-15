# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.routes.datasets import router as datasets_router
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportTarget,
    Metric,
    SemanticModel,
    SemanticModelSource,
    User,
)
from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class DatasetApiContext:
    client: TestClient
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
        yield DatasetApiContext(client=client, **ids)

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
        model_source = SemanticModelSource(
            semantic_model_id=active_model.id,
            target_id=target.id,
            alias="sales",
            source_role="fact",
            ordinal=0,
        )
        session.add(model_source)

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
