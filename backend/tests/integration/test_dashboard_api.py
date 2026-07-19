# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_query_principal
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.db.models import User
from bi_system.identity import QueryPrincipal
from bi_system.main import create_app
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

try:
    dashboard_routes = import_module("bi_system.api.routes.dashboards")
    dashboards_router = cast(APIRouter, dashboard_routes.router)
    import_module("bi_system.db.models.dashboards")
except ModuleNotFoundError as error:
    pending_modules = {
        "bi_system.api.routes.dashboards",
        "bi_system.dashboards.service",
    }
    if error.name not in pending_modules:
        raise
    pytest.skip("M3-R1 dashboard API is not available yet", allow_module_level=True)


@dataclass(frozen=True)
class DashboardApiContext:
    client: TestClient
    application: FastAPI
    workspace_id: UUID
    owner_user_id: UUID
    viewer_user_id: UUID


@pytest.fixture
def dashboard_api_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[DashboardApiContext]:
    workspace_id = uuid4()
    database_path = tmp_path / "dashboard-api.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("BI_WORKSPACE_ID", str(workspace_id))
    clear_settings_cache()
    application = create_app()
    application.include_router(dashboards_router, prefix="/api/v1/dashboards")

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        session_factory = cast(sessionmaker[Session], application.state.session_factory)
        with session_factory.begin() as session:
            owner = User(
                workspace_id=workspace_id,
                username="dashboard-owner",
                display_name="仪表盘所有者",
                password_hash="not-used-in-test",
            )
            viewer = User(
                workspace_id=workspace_id,
                username="dashboard-viewer",
                display_name="仪表盘查看者",
                password_hash="not-used-in-test",
            )
            session.add_all([owner, viewer])
            session.flush()
            owner_user_id = owner.id
            viewer_user_id = viewer.id

        _set_principal(
            application,
            user_id=owner_user_id,
            workspace_id=workspace_id,
            permissions={
                "dashboards:view",
                "dashboards:edit",
                "dashboards:share",
                "dashboard_templates:manage",
                "dashboard_templates:publish",
            },
        )
        yield DashboardApiContext(
            client=client,
            application=application,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            viewer_user_id=viewer_user_id,
        )

    clear_settings_cache()


def _set_principal(
    application: FastAPI,
    *,
    user_id: UUID,
    workspace_id: UUID,
    permissions: set[str],
) -> None:
    principal = QueryPrincipal(
        user_id=user_id,
        workspace_id=workspace_id,
        permissions=frozenset(permissions),
    )
    application.dependency_overrides[get_query_principal] = lambda: principal


def _create_dashboard(context: DashboardApiContext) -> dict[str, object]:
    response = cast(
        Response,
        context.client.post(
            "/api/v1/dashboards",
            json={"name": "经营驾驶舱", "description": "核心经营指标"},
        ),
    )

    assert response.status_code == 201
    payload = cast(dict[str, object], response.json())
    assert payload["name"] == "经营驾驶舱"
    assert payload["status"] == "draft"
    assert payload["revision"] == 1
    assert payload["current_version"] == 1
    return payload


def _version_payload() -> dict[str, object]:
    page_id = str(uuid4())
    component_id = str(uuid4())
    return {
        "base_version": 1,
        "expected_revision": 1,
        "pages": [{"page_id": page_id, "title": "经营总览", "ordinal": 0}],
        "components": [
            {
                "component_id": component_id,
                "page_id": page_id,
                "component_type": "rich_text",
                "config_version": 1,
                "config": {"schema_version": 1, "content": []},
            }
        ],
        "layouts": [
            {
                "profile": "desktop",
                "items": [
                    {
                        "component_id": component_id,
                        "x": 0,
                        "y": 0,
                        "width": 6,
                        "height": 4,
                        "min_width": 2,
                        "min_height": 2,
                    }
                ],
            },
            {
                "profile": "mobile",
                "items": [
                    {
                        "component_id": component_id,
                        "x": 0,
                        "y": 0,
                        "width": 4,
                        "height": 4,
                        "min_width": 1,
                        "min_height": 2,
                    }
                ],
            },
        ],
    }


def test_dashboard_api_saves_version_and_rejects_stale_revision(
    dashboard_api_context: DashboardApiContext,
) -> None:
    dashboard = _create_dashboard(dashboard_api_context)
    dashboard_id = dashboard["id"]
    payload = _version_payload()

    saved = cast(
        Response,
        dashboard_api_context.client.post(
            f"/api/v1/dashboards/{dashboard_id}/versions",
            json=payload,
        ),
    )
    stale = cast(
        Response,
        dashboard_api_context.client.post(
            f"/api/v1/dashboards/{dashboard_id}/versions",
            json=payload,
        ),
    )

    assert saved.status_code == 201
    assert saved.json()["revision"] == 2
    assert saved.json()["current_version"] == 2
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "dashboard_revision_conflict"


def test_dashboard_api_activates_and_instantiates_published_template_version(
    dashboard_api_context: DashboardApiContext,
) -> None:
    dashboard = _create_dashboard(dashboard_api_context)
    dashboard_id = dashboard["id"]
    version_id = dashboard["current_version_id"]
    activated = cast(
        Response,
        dashboard_api_context.client.post(
            f"/api/v1/dashboards/{dashboard_id}/activate",
            json={"expected_revision": 1},
        ),
    )
    template = cast(
        Response,
        dashboard_api_context.client.post(
            "/api/v1/dashboard-templates",
            json={
                "name": "经营模板",
                "source_dashboard_version_id": version_id,
                "visibility": "workspace",
            },
        ),
    )
    template_id = template.json()["id"]
    published = cast(
        Response,
        dashboard_api_context.client.post(
            f"/api/v1/dashboard-templates/{template_id}/publish",
            json={"expected_revision": 1},
        ),
    )
    instantiated = cast(
        Response,
        dashboard_api_context.client.post(
            f"/api/v1/dashboard-templates/{template_id}/instantiate",
            json={
                "name": "模板实例",
                "template_version_id": published.json()["version_id"],
            },
        ),
    )
    referenced = cast(
        Response,
        dashboard_api_context.client.request(
            "DELETE",
            f"/api/v1/dashboards/{dashboard_id}",
            params={"expected_revision": 2},
        ),
    )

    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert template.status_code == 201
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert instantiated.status_code == 201
    assert instantiated.json()["name"] == "模板实例"
    assert instantiated.json()["current_version"] == 1
    assert referenced.status_code == 409
    assert referenced.json()["detail"]["code"] == "dashboard_reference_conflict"
    assert referenced.json()["detail"]["impact"] == {
        "resource_type": "dashboard_template",
        "count": 1,
        "items": [
            {
                "template_id": template_id,
                "template_name": "经营模板",
                "template_version_id": published.json()["version_id"],
                "version": 1,
            }
        ],
    }


def test_dashboard_api_requires_coarse_and_resource_view_permissions(
    dashboard_api_context: DashboardApiContext,
) -> None:
    dashboard = _create_dashboard(dashboard_api_context)
    dashboard_id = dashboard["id"]

    _set_principal(
        dashboard_api_context.application,
        user_id=dashboard_api_context.viewer_user_id,
        workspace_id=dashboard_api_context.workspace_id,
        permissions={"dashboards:view"},
    )
    without_grant = cast(
        Response,
        dashboard_api_context.client.get(f"/api/v1/dashboards/{dashboard_id}"),
    )

    _set_principal(
        dashboard_api_context.application,
        user_id=dashboard_api_context.owner_user_id,
        workspace_id=dashboard_api_context.workspace_id,
        permissions={"dashboards:view", "dashboards:share"},
    )
    replaced = cast(
        Response,
        dashboard_api_context.client.put(
            f"/api/v1/dashboards/{dashboard_id}/permissions",
            json={
                "permissions": [
                    {
                        "subject_type": "user",
                        "subject_id": str(dashboard_api_context.viewer_user_id),
                        "capability": "view",
                    }
                ]
            },
        ),
    )

    _set_principal(
        dashboard_api_context.application,
        user_id=dashboard_api_context.viewer_user_id,
        workspace_id=dashboard_api_context.workspace_id,
        permissions=set(),
    )
    without_coarse_permission = cast(
        Response,
        dashboard_api_context.client.get(f"/api/v1/dashboards/{dashboard_id}"),
    )

    _set_principal(
        dashboard_api_context.application,
        user_id=dashboard_api_context.viewer_user_id,
        workspace_id=dashboard_api_context.workspace_id,
        permissions={"dashboards:view"},
    )
    authorized = cast(
        Response,
        dashboard_api_context.client.get(f"/api/v1/dashboards/{dashboard_id}"),
    )

    assert without_grant.status_code == 403
    assert replaced.status_code == 200
    assert without_coarse_permission.status_code == 403
    assert authorized.status_code == 200
    assert authorized.json()["id"] == dashboard_id


def test_dashboard_api_hides_cross_workspace_resource_before_grant_check(
    dashboard_api_context: DashboardApiContext,
) -> None:
    dashboard = _create_dashboard(dashboard_api_context)
    dashboard_id = dashboard["id"]
    _set_principal(
        dashboard_api_context.application,
        user_id=dashboard_api_context.owner_user_id,
        workspace_id=uuid4(),
        permissions={"dashboards:view"},
    )

    response = cast(
        Response,
        dashboard_api_context.client.get(f"/api/v1/dashboards/{dashboard_id}"),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "dashboard_not_found"
