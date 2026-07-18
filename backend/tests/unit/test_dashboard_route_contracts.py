# pyright: reportAny=false, reportUnknownMemberType=false
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_database_session, get_query_principal
from bi_system.api.routes.dashboards import router
from bi_system.db.base import Base
from bi_system.db.models.identity import User
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session


@pytest.fixture
def dashboard_api(
    tmp_path: Path,
) -> Generator[tuple[TestClient, dict[str, UUID], dict[str, QueryPrincipal]]]:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'api.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    foreign_workspace_id = uuid4()
    with session_factory.begin() as session:
        owner = User(
            workspace_id=workspace_id,
            username="api.owner",
            display_name="API Owner",
            password_hash="hash",
            must_change_password=False,
        )
        viewer = User(
            workspace_id=workspace_id,
            username="api.viewer",
            display_name="API Viewer",
            password_hash="hash",
            must_change_password=False,
        )
        foreign = User(
            workspace_id=foreign_workspace_id,
            username="foreign.api",
            display_name="Foreign API",
            password_hash="hash",
            must_change_password=False,
        )
        session.add_all([owner, viewer, foreign])
        session.flush()
        ids = {
            "workspace": workspace_id,
            "owner": owner.id,
            "viewer": viewer.id,
            "foreign_workspace": foreign_workspace_id,
            "foreign": foreign.id,
        }

    application = FastAPI()
    application.include_router(router, prefix="/dashboards")

    def session_dependency() -> Generator[Session]:
        with session_factory() as session:
            yield session

    owner_principal = QueryPrincipal(
        user_id=ids["owner"],
        workspace_id=ids["workspace"],
        permissions=frozenset(
            {"dashboards:view", "dashboards:edit", "dashboards:share", "dashboards:export"}
        ),
    )
    actor = {"value": owner_principal}
    application.dependency_overrides[get_database_session] = session_dependency
    application.dependency_overrides[get_query_principal] = lambda: actor["value"]
    try:
        with TestClient(application) as client:
            yield client, ids, actor
    finally:
        engine.dispose()


def test_dashboard_api_versions_permissions_and_workspace_boundary(
    dashboard_api: tuple[TestClient, dict[str, UUID], dict[str, QueryPrincipal]],
) -> None:
    client, ids, actor = dashboard_api
    created = cast(Response, client.post("/dashboards", json={"name": "API dashboard"}))
    dashboard_id = created.json()["id"]
    saved = cast(
        Response,
        client.post(
            f"/dashboards/{dashboard_id}/versions",
            json={
                "base_version": 1,
                "expected_revision": 1,
                "pages": [],
                "components": [],
                "layouts": [
                    {"profile": "desktop", "items": []},
                    {"profile": "mobile", "items": []},
                ],
            },
        ),
    )

    assert created.status_code == 201
    assert created.json()["revision"] == 1
    assert created.json()["current_version"] == 1
    assert created.json()["current_version_id"]
    assert saved.status_code == 201
    assert saved.json()["revision"] == 2
    assert saved.json()["current_version"] == 2

    actor["value"] = QueryPrincipal(
        user_id=ids["viewer"],
        workspace_id=ids["workspace"],
        permissions=frozenset({"dashboards:view"}),
    )
    forbidden = cast(Response, client.get(f"/dashboards/{dashboard_id}"))
    assert forbidden.status_code == 403

    actor["value"] = QueryPrincipal(
        user_id=ids["owner"],
        workspace_id=ids["workspace"],
        permissions=frozenset({"dashboards:view", "dashboards:edit", "dashboards:share"}),
    )
    granted = cast(
        Response,
        client.put(
            f"/dashboards/{dashboard_id}/permissions",
            json={
                "permissions": [
                    {
                        "subject_type": "user",
                        "subject_id": str(ids["viewer"]),
                        "capability": "view",
                    }
                ]
            },
        ),
    )
    assert granted.status_code == 200

    actor["value"] = QueryPrincipal(
        user_id=ids["viewer"],
        workspace_id=ids["workspace"],
        permissions=frozenset({"dashboards:view"}),
    )
    readable = cast(Response, client.get(f"/dashboards/{dashboard_id}"))
    assert readable.status_code == 200
    assert readable.json()["capabilities"] == ["view"]

    actor["value"] = QueryPrincipal(
        user_id=ids["foreign"],
        workspace_id=ids["foreign_workspace"],
        permissions=frozenset({"dashboards:view"}),
    )
    hidden = cast(Response, client.get(f"/dashboards/{dashboard_id}"))
    assert hidden.status_code == 404
