# pyright: reportAny=false, reportUnknownMemberType=false
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_database_session, get_query_principal
from bi_system.api.routes.dashboards import router, template_router
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
    application.include_router(template_router, prefix="/dashboard-templates")

    def session_dependency() -> Generator[Session]:
        with session_factory() as session:
            yield session

    owner_principal = QueryPrincipal(
        user_id=ids["owner"],
        workspace_id=ids["workspace"],
        permissions=frozenset(
            {
                "dashboards:view",
                "dashboards:edit",
                "dashboards:share",
                "dashboards:export",
                "dashboard_templates:manage",
                "dashboard_templates:publish",
            }
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


def test_dashboard_activation_and_template_lifecycle_routes(
    dashboard_api: tuple[TestClient, dict[str, UUID], dict[str, QueryPrincipal]],
) -> None:
    client, _ids, actor = dashboard_api
    created = cast(Response, client.post("/dashboards", json={"name": "Lifecycle source"}))
    dashboard_id = created.json()["id"]
    version_id = created.json()["current_version_id"]
    activated = cast(
        Response,
        client.post(
            f"/dashboards/{dashboard_id}/activate",
            json={"expected_revision": 1},
        ),
    )
    template = cast(
        Response,
        client.post(
            "/dashboard-templates",
            json={
                "name": "Team lifecycle template",
                "source_dashboard_version_id": version_id,
                "visibility": "workspace",
            },
        ),
    )
    template_id = template.json()["id"]
    template_v1_id = template.json()["version_id"]
    unpublished = cast(
        Response,
        client.post(
            f"/dashboard-templates/{template_id}/instantiate",
            json={
                "name": "Unpublished instance",
                "template_version_id": template_v1_id,
            },
        ),
    )
    owner = actor["value"]
    actor["value"] = QueryPrincipal(
        user_id=owner.user_id,
        workspace_id=owner.workspace_id,
        permissions=owner.permissions - {"dashboard_templates:publish"},
    )
    forbidden_publish = cast(
        Response,
        client.post(
            f"/dashboard-templates/{template_id}/publish",
            json={"expected_revision": 1},
        ),
    )
    actor["value"] = owner
    published_v1 = cast(
        Response,
        client.post(
            f"/dashboard-templates/{template_id}/publish",
            json={"expected_revision": 1},
        ),
    )
    draft_v2 = cast(
        Response,
        client.post(
            f"/dashboard-templates/{template_id}/versions",
            json={
                "source_dashboard_version_id": version_id,
                "expected_revision": 2,
            },
        ),
    )
    pinned_instance = cast(
        Response,
        client.post(
            f"/dashboard-templates/{template_id}/instantiate",
            json={
                "name": "Pinned V1",
                "description": None,
                "template_version_id": template_v1_id,
            },
        ),
    )
    published_v2 = cast(
        Response,
        client.post(
            f"/dashboard-templates/{template_id}/publish",
            json={"expected_revision": 3},
        ),
    )

    assert created.status_code == 201
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert template.status_code == 201
    assert unpublished.status_code == 409
    assert unpublished.json()["detail"]["code"] == "dashboard_template_version_unpublished"
    assert forbidden_publish.status_code == 403
    assert forbidden_publish.json()["detail"]["code"] == "dashboard_template_publish_forbidden"
    assert published_v1.json()["status"] == "published"
    assert draft_v2.status_code == 201
    assert draft_v2.json()["status"] == "draft"
    assert draft_v2.json()["version_id"] != template_v1_id
    assert pinned_instance.status_code == 201
    assert pinned_instance.json()["current_version"] == 1
    assert published_v2.json()["status"] == "published"
    assert published_v2.json()["revision"] == 4
