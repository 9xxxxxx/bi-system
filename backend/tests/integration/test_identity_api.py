# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_query_principal
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.db.models import Role, User
from bi_system.identity import QueryPrincipal
from bi_system.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def identity_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FastAPI, UUID, UUID]]:
    workspace_id = uuid4()
    foreign_workspace_id = uuid4()
    database_path = tmp_path / "identity-api.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("BI_WORKSPACE_ID", str(workspace_id))
    clear_settings_cache()
    application = create_app()

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        session_factory = cast(sessionmaker[Session], application.state.session_factory)
        with session_factory.begin() as session:
            active_user = User(
                workspace_id=workspace_id,
                username="analyst",
                display_name="数据分析员",
                password_hash="sensitive-password-hash",
            )
            session.add_all(
                [
                    active_user,
                    User(
                        workspace_id=workspace_id,
                        username="disabled",
                        display_name="停用用户",
                        password_hash="hidden",
                        status="disabled",
                    ),
                    User(
                        workspace_id=foreign_workspace_id,
                        username="foreign",
                        display_name="其他工作区用户",
                        password_hash="hidden",
                    ),
                ],
            )
            active_role = Role(
                workspace_id=workspace_id,
                code="analyst",
                name="分析员",
                description="可查看授权数据",
                permissions=["datasets:query"],
            )
            session.add_all(
                [
                    active_role,
                    Role(
                        workspace_id=workspace_id,
                        code="archived",
                        name="已归档角色",
                        status="archived",
                    ),
                    Role(
                        workspace_id=foreign_workspace_id,
                        code="foreign",
                        name="其他工作区角色",
                    ),
                ],
            )
            session.flush()

        manager = QueryPrincipal(
            user_id=active_user.id,
            workspace_id=workspace_id,
            permissions=frozenset({"datasets:manage"}),
        )
        application.dependency_overrides[get_query_principal] = lambda: manager
        yield client, application, active_user.id, active_role.id

    clear_settings_cache()


def test_identity_directory_returns_only_active_workspace_resources(
    identity_api: tuple[TestClient, FastAPI, UUID, UUID],
) -> None:
    client, _application, user_id, role_id = identity_api

    users = cast(Response, client.get("/api/v1/identity/users"))
    roles = cast(Response, client.get("/api/v1/identity/roles"))

    assert users.status_code == 200
    assert users.json() == [
        {"id": str(user_id), "username": "analyst", "display_name": "数据分析员"}
    ]
    assert roles.status_code == 200
    assert roles.json() == [
        {
            "id": str(role_id),
            "code": "analyst",
            "name": "分析员",
            "description": "可查看授权数据",
        }
    ]
    assert "password_hash" not in users.text
    assert "permissions" not in roles.text


def test_identity_directory_requires_dataset_management_permission(
    identity_api: tuple[TestClient, FastAPI, UUID, UUID],
) -> None:
    client, application, user_id, _role_id = identity_api
    application.dependency_overrides[get_query_principal] = lambda: QueryPrincipal(
        user_id=user_id,
        workspace_id=uuid4(),
        permissions=frozenset({"datasets:read"}),
    )

    response = cast(Response, client.get("/api/v1/identity/users"))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "identity_directory_forbidden"
