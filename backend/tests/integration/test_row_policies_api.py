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
from bi_system.db.models import (
    Dataset,
    DatasetField,
    Role,
    RowPolicy,
    RowPolicyAssignment,
    SemanticModel,
    User,
)
from bi_system.identity import QueryPrincipal
from bi_system.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class RowPolicyApiContext:
    client: TestClient
    application: FastAPI
    workspace_id: UUID
    owner_user_id: UUID
    analyst_user_id: UUID
    analyst_role_id: UUID
    foreign_user_id: UUID
    foreign_role_id: UUID
    dataset_id: UUID
    foreign_dataset_id: UUID
    region_field_id: UUID
    amount_field_id: UUID
    active_policy_id: UUID
    foreign_policy_id: UUID


@pytest.fixture
def row_policy_api_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[RowPolicyApiContext]:
    workspace_id = uuid4()
    database_path = tmp_path / "row-policies.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("BI_WORKSPACE_ID", str(workspace_id))
    clear_settings_cache()
    application = create_app()

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        session_factory = cast(sessionmaker[Session], application.state.session_factory)
        ids = _seed_row_policies(session_factory, workspace_id=workspace_id)
        manager = QueryPrincipal(
            user_id=ids["owner_user_id"],
            workspace_id=workspace_id,
            permissions=frozenset({"datasets:manage"}),
        )
        application.dependency_overrides[get_query_principal] = lambda: manager
        yield RowPolicyApiContext(
            client=client,
            application=application,
            workspace_id=workspace_id,
            **ids,
        )

    clear_settings_cache()


def _seed_row_policies(
    session_factory: sessionmaker[Session],
    *,
    workspace_id: UUID,
) -> dict[str, UUID]:
    foreign_workspace_id = uuid4()
    with session_factory.begin() as session:
        owner = User(
            workspace_id=workspace_id,
            username="policy-admin",
            display_name="策略管理员",
            password_hash="not-used-in-test",
        )
        analyst = User(
            workspace_id=workspace_id,
            username="analyst",
            display_name="分析员",
            password_hash="not-used-in-test",
        )
        foreign_user = User(
            workspace_id=foreign_workspace_id,
            username="foreign-analyst",
            display_name="外部分析员",
            password_hash="not-used-in-test",
        )
        analyst_role = Role(
            workspace_id=workspace_id,
            code="analyst",
            name="分析员",
            permissions=[],
        )
        foreign_role = Role(
            workspace_id=foreign_workspace_id,
            code="foreign-analyst",
            name="外部分析员",
            permissions=[],
        )
        session.add_all([owner, analyst, foreign_user, analyst_role, foreign_role])
        session.flush()

        model = SemanticModel(
            workspace_id=workspace_id,
            name="销售模型",
            version=1,
            status="active",
            created_by_user_id=owner.id,
        )
        foreign_model = SemanticModel(
            workspace_id=foreign_workspace_id,
            name="外部销售模型",
            version=1,
            status="active",
            created_by_user_id=foreign_user.id,
        )
        session.add_all([model, foreign_model])
        session.flush()
        dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=model.id,
            name="销售数据集",
            version=1,
            status="active",
            created_by_user_id=owner.id,
        )
        foreign_dataset = Dataset(
            workspace_id=foreign_workspace_id,
            semantic_model_id=foreign_model.id,
            name="外部销售数据集",
            version=1,
            status="active",
            created_by_user_id=foreign_user.id,
        )
        session.add_all([dataset, foreign_dataset])
        session.flush()
        region = DatasetField(
            dataset_id=dataset.id,
            name="region",
            label="区域",
            field_kind="calculated",
            field_role="dimension",
            data_type="string",
            expression={"op": "literal", "value": ""},
            ordinal=0,
        )
        amount = DatasetField(
            dataset_id=dataset.id,
            name="amount",
            label="销售额",
            field_kind="calculated",
            field_role="measure",
            data_type="decimal",
            expression={"op": "literal", "value": 0},
            ordinal=1,
        )
        session.add_all([region, amount])
        session.flush()
        active_policy = RowPolicy(
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            name="已有区域策略",
            version=1,
            effect="allow",
            expression={
                "kind": "comparison",
                "field_id": str(region.id),
                "operator": "eq",
                "value": "华东",
            },
            status="active",
            created_by_user_id=owner.id,
        )
        foreign_policy = RowPolicy(
            workspace_id=foreign_workspace_id,
            dataset_id=foreign_dataset.id,
            name="外部策略",
            version=1,
            effect="allow",
            expression={
                "kind": "null",
                "field_id": str(uuid4()),
                "is_null": False,
            },
            status="draft",
            created_by_user_id=foreign_user.id,
        )
        session.add_all([active_policy, foreign_policy])
        session.flush()
        session.add(
            RowPolicyAssignment(
                row_policy_id=active_policy.id,
                role_id=analyst_role.id,
            )
        )
    return {
        "owner_user_id": owner.id,
        "analyst_user_id": analyst.id,
        "analyst_role_id": analyst_role.id,
        "foreign_user_id": foreign_user.id,
        "foreign_role_id": foreign_role.id,
        "dataset_id": dataset.id,
        "foreign_dataset_id": foreign_dataset.id,
        "region_field_id": region.id,
        "amount_field_id": amount.id,
        "active_policy_id": active_policy.id,
        "foreign_policy_id": foreign_policy.id,
    }


def _policy_payload(context: RowPolicyApiContext) -> dict[str, object]:
    return {
        "dataset_id": str(context.dataset_id),
        "name": "华东区域策略",
        "effect": "allow",
        "expression": {
            "kind": "comparison",
            "field_id": str(context.region_field_id),
            "operator": "eq",
            "value": "华东",
        },
    }


def test_row_policy_api_creates_lists_and_reads_draft(
    row_policy_api_context: RowPolicyApiContext,
) -> None:
    created = cast(
        Response,
        row_policy_api_context.client.post(
            "/api/v1/row-policies",
            json=_policy_payload(row_policy_api_context),
        ),
    )

    assert created.status_code == 201
    assert created.json()["status"] == "draft"
    assert created.json()["version"] == 1
    assert created.json()["user_ids"] == []
    listed = cast(
        Response,
        row_policy_api_context.client.get(
            f"/api/v1/row-policies?dataset_id={row_policy_api_context.dataset_id}"
        ),
    )
    stored = cast(
        Response,
        row_policy_api_context.client.get(f"/api/v1/row-policies/{created.json()['id']}"),
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert {
        key: value
        for key, value in stored.json().items()
        if key not in {"created_at", "updated_at"}
    } == {
        key: value
        for key, value in created.json().items()
        if key not in {"created_at", "updated_at"}
    }


def test_row_policy_versions_copy_bindings_and_disable_previous_active(
    row_policy_api_context: RowPolicyApiContext,
) -> None:
    original = cast(
        Response,
        row_policy_api_context.client.get(
            f"/api/v1/row-policies/{row_policy_api_context.active_policy_id}"
        ),
    ).json()
    version = cast(
        Response,
        row_policy_api_context.client.post(
            f"/api/v1/row-policies/{row_policy_api_context.active_policy_id}/versions",
            json={"effect": "deny"},
        ),
    )

    assert version.status_code == 201
    assert version.json()["status"] == "draft"
    assert version.json()["version"] == 2
    assert version.json()["series_id"] == original["series_id"]
    assert version.json()["role_ids"] == [str(row_policy_api_context.analyst_role_id)]
    assert version.json()["effect"] == "deny"

    activated = cast(
        Response,
        row_policy_api_context.client.post(f"/api/v1/row-policies/{version.json()['id']}/activate"),
    )
    previous = cast(
        Response,
        row_policy_api_context.client.get(
            f"/api/v1/row-policies/{row_policy_api_context.active_policy_id}"
        ),
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert previous.json()["status"] == "disabled"
    assert previous.json()["effect"] == original["effect"]
    assert previous.json()["expression"] == original["expression"]


def test_row_policy_activation_requires_valid_workspace_bindings(
    row_policy_api_context: RowPolicyApiContext,
) -> None:
    created = cast(
        Response,
        row_policy_api_context.client.post(
            "/api/v1/row-policies",
            json=_policy_payload(row_policy_api_context),
        ),
    )
    policy_id = created.json()["id"]
    unbound = cast(
        Response,
        row_policy_api_context.client.post(f"/api/v1/row-policies/{policy_id}/activate"),
    )
    foreign = cast(
        Response,
        row_policy_api_context.client.put(
            f"/api/v1/row-policies/{policy_id}/bindings",
            json={"user_ids": [str(row_policy_api_context.foreign_user_id)]},
        ),
    )
    bound = cast(
        Response,
        row_policy_api_context.client.put(
            f"/api/v1/row-policies/{policy_id}/bindings",
            json={
                "user_ids": [str(row_policy_api_context.analyst_user_id)],
                "role_ids": [str(row_policy_api_context.analyst_role_id)],
            },
        ),
    )
    activated = cast(
        Response,
        row_policy_api_context.client.post(f"/api/v1/row-policies/{policy_id}/activate"),
    )

    assert unbound.status_code == 409
    assert unbound.json()["detail"]["code"] == "row_policy_activation_conflict"
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "row_policy_binding_resource_not_found"
    assert bound.status_code == 200
    assert bound.json()["user_ids"] == [str(row_policy_api_context.analyst_user_id)]
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"


def test_row_policy_api_validates_dataset_field_and_filter_types(
    row_policy_api_context: RowPolicyApiContext,
) -> None:
    foreign_dataset = _policy_payload(row_policy_api_context)
    foreign_dataset["dataset_id"] = str(row_policy_api_context.foreign_dataset_id)
    foreign = cast(
        Response,
        row_policy_api_context.client.post(
            "/api/v1/row-policies",
            json=foreign_dataset,
        ),
    )
    unknown_field = _policy_payload(row_policy_api_context)
    expression = cast(dict[str, object], unknown_field["expression"])
    expression["field_id"] = str(uuid4())
    unknown = cast(
        Response,
        row_policy_api_context.client.post(
            "/api/v1/row-policies",
            json=unknown_field,
        ),
    )
    wrong_type = _policy_payload(row_policy_api_context)
    wrong_expression = cast(dict[str, object], wrong_type["expression"])
    wrong_expression["field_id"] = str(row_policy_api_context.amount_field_id)
    wrong_expression["value"] = "not-a-number"
    invalid_type = cast(
        Response,
        row_policy_api_context.client.post(
            "/api/v1/row-policies",
            json=wrong_type,
        ),
    )

    assert foreign.status_code == 404
    assert unknown.status_code == 422
    assert invalid_type.status_code == 422
    assert invalid_type.json()["detail"]["code"] == "invalid_row_policy_configuration"


def test_row_policy_activation_revalidates_stored_expression(
    row_policy_api_context: RowPolicyApiContext,
) -> None:
    created = cast(
        Response,
        row_policy_api_context.client.post(
            "/api/v1/row-policies",
            json=_policy_payload(row_policy_api_context),
        ),
    )
    policy_id = UUID(created.json()["id"])
    session_factory = cast(
        sessionmaker[Session], row_policy_api_context.application.state.session_factory
    )
    with session_factory.begin() as session:
        policy = session.get(RowPolicy, policy_id)
        assert policy is not None
        policy.expression = {"kind": "raw_sql", "sql": "region = current_user"}
        session.add(
            RowPolicyAssignment(
                row_policy_id=policy_id,
                user_id=row_policy_api_context.analyst_user_id,
            )
        )

    activated = cast(
        Response,
        row_policy_api_context.client.post(f"/api/v1/row-policies/{policy_id}/activate"),
    )

    assert activated.status_code == 422
    assert activated.json()["detail"]["code"] == "invalid_row_policy_configuration"


def test_row_policy_api_hides_foreign_resources_and_requires_permission(
    row_policy_api_context: RowPolicyApiContext,
) -> None:
    hidden = cast(
        Response,
        row_policy_api_context.client.get(
            f"/api/v1/row-policies/{row_policy_api_context.foreign_policy_id}"
        ),
    )
    viewer = QueryPrincipal(
        user_id=row_policy_api_context.owner_user_id,
        workspace_id=row_policy_api_context.workspace_id,
    )
    row_policy_api_context.application.dependency_overrides[get_query_principal] = lambda: viewer
    forbidden = cast(
        Response,
        row_policy_api_context.client.get("/api/v1/row-policies"),
    )

    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "row_policy_not_found"
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "row_policy_manage_forbidden"
