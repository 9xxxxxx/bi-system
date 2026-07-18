from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bi_system.dashboards.contracts import (
    CreateDashboard,
    CreateDashboardTemplate,
    ReplaceDashboardPermissions,
    SaveDashboardVersion,
)
from bi_system.dashboards.errors import (
    DashboardConflictError,
    DashboardForbiddenError,
    DashboardNotFoundError,
)
from bi_system.dashboards.service import (
    create_dashboard,
    create_dashboard_template,
    delete_dashboard,
    get_dashboard,
    list_dashboards,
    replace_dashboard_permissions,
    restore_dashboard,
    save_dashboard_version,
)
from bi_system.db.base import Base
from bi_system.db.models.dashboards import DashboardVersion
from bi_system.db.models.identity import User
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class DashboardResources:
    workspace_id: UUID
    owner_id: UUID
    viewer_id: UUID
    foreign_workspace_id: UUID
    foreign_user_id: UUID


@pytest.fixture
def dashboard_store(
    tmp_path: Path,
) -> Iterator[tuple[sessionmaker[Session], DashboardResources, Engine]]:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'dashboards.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    foreign_workspace_id = uuid4()
    with session_factory.begin() as session:
        owner = User(
            workspace_id=workspace_id,
            username="dashboard.owner",
            display_name="Dashboard Owner",
            password_hash="hash",
            must_change_password=False,
        )
        viewer = User(
            workspace_id=workspace_id,
            username="dashboard.viewer",
            display_name="Dashboard Viewer",
            password_hash="hash",
            must_change_password=False,
        )
        foreign = User(
            workspace_id=foreign_workspace_id,
            username="foreign.viewer",
            display_name="Foreign Viewer",
            password_hash="hash",
            must_change_password=False,
        )
        session.add_all([owner, viewer, foreign])
        session.flush()
        resources = DashboardResources(
            workspace_id=workspace_id,
            owner_id=owner.id,
            viewer_id=viewer.id,
            foreign_workspace_id=foreign_workspace_id,
            foreign_user_id=foreign.id,
        )
    try:
        yield session_factory, resources, engine
    finally:
        engine.dispose()


def owner_principal(resources: DashboardResources) -> QueryPrincipal:
    return QueryPrincipal(
        user_id=resources.owner_id,
        workspace_id=resources.workspace_id,
        permissions=frozenset(
            {
                "dashboards:view",
                "dashboards:edit",
                "dashboards:share",
                "dashboards:export",
                "dashboard_templates:manage",
            }
        ),
    )


def aggregate_request(
    *,
    base_version: int = 1,
    expected_revision: int = 1,
    global_filter: dict[str, object] | None = None,
) -> SaveDashboardVersion:
    page_id = uuid4()
    component_id = uuid4()
    item = {
        "component_id": component_id,
        "x": 0,
        "y": 0,
        "width": 4,
        "height": 3,
        "min_width": 2,
        "min_height": 2,
    }
    return SaveDashboardVersion.model_validate(
        {
            "base_version": base_version,
            "expected_revision": expected_revision,
            "global_filter": global_filter,
            "pages": [{"page_id": page_id, "title": "Overview", "ordinal": 0}],
            "components": [
                {
                    "component_id": component_id,
                    "page_id": page_id,
                    "component_type": "kpi",
                    "config_version": 1,
                    "config": {"schema_version": 1, "title": "Revenue"},
                }
            ],
            "layouts": [
                {"profile": "desktop", "items": [item]},
                {"profile": "mobile", "items": [item]},
            ],
        }
    )


def test_dashboard_lifecycle_saves_immutable_aggregate_versions(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    with session_factory() as session:
        created = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Executive overview"),
        )
        saved = save_dashboard_version(
            session,
            principal=principal,
            dashboard_id=created.id,
            request=aggregate_request(
                global_filter={"kind": "comparison", "operator": "eq", "value": "North"}
            ),
        )
    with session_factory() as session:
        version_count = session.scalar(
            select(func.count(DashboardVersion.id)).where(
                DashboardVersion.dashboard_id == created.id
            )
        )
        reopened = get_dashboard(session, principal=principal, dashboard_id=created.id)

    assert created.revision == 1
    assert created.current_version == 1
    assert created.pages == []
    assert saved.revision == 2
    assert saved.current_version == 2
    assert saved.current_version_id != created.current_version_id
    assert saved.global_filter == {
        "kind": "comparison",
        "operator": "eq",
        "value": "North",
    }
    assert saved.pages[0].components[0].config["title"] == "Revenue"
    assert reopened.current_version_id == saved.current_version_id
    assert version_count == 2


def test_dashboard_save_rejects_stale_revision_and_base_version(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    with session_factory() as session:
        created = create_dashboard(
            session, principal=principal, request=CreateDashboard(name="Concurrent")
        )
        save_dashboard_version(
            session,
            principal=principal,
            dashboard_id=created.id,
            request=aggregate_request(),
        )
    with session_factory() as session, pytest.raises(DashboardConflictError) as stale:
        save_dashboard_version(
            session,
            principal=principal,
            dashboard_id=created.id,
            request=aggregate_request(),
        )
    assert stale.value.code == "dashboard_revision_conflict"

    with session_factory() as session, pytest.raises(DashboardConflictError) as base:
        save_dashboard_version(
            session,
            principal=principal,
            dashboard_id=created.id,
            request=aggregate_request(base_version=1, expected_revision=2),
        )
    assert base.value.code == "dashboard_base_version_conflict"


def test_dashboard_permissions_and_workspace_isolation(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    owner = owner_principal(resources)
    viewer = QueryPrincipal(
        user_id=resources.viewer_id,
        workspace_id=resources.workspace_id,
        permissions=frozenset({"dashboards:view"}),
    )
    foreign = QueryPrincipal(
        user_id=resources.foreign_user_id,
        workspace_id=resources.foreign_workspace_id,
        permissions=frozenset({"dashboards:view"}),
    )
    with session_factory() as session:
        created = create_dashboard(session, principal=owner, request=CreateDashboard(name="Shared"))
    with session_factory() as session, pytest.raises(DashboardForbiddenError):
        get_dashboard(session, principal=viewer, dashboard_id=created.id)
    with session_factory() as session, pytest.raises(DashboardNotFoundError):
        get_dashboard(session, principal=foreign, dashboard_id=created.id)

    with session_factory() as session:
        replaced = replace_dashboard_permissions(
            session,
            principal=owner,
            dashboard_id=created.id,
            request=ReplaceDashboardPermissions.model_validate(
                {
                    "permissions": [
                        {
                            "subject_type": "user",
                            "subject_id": resources.viewer_id,
                            "capability": "view",
                        }
                    ]
                }
            ),
        )
    with session_factory() as session:
        visible = get_dashboard(session, principal=viewer, dashboard_id=created.id)
        listed = list_dashboards(session, principal=viewer, offset=0, limit=50)

    assert replaced.revision == 2
    assert visible.id == created.id
    assert visible.capabilities == ["view"]
    assert listed.total == 1


def test_dashboard_delete_restore_and_trash_listing(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    with session_factory() as session:
        created = create_dashboard(
            session, principal=principal, request=CreateDashboard(name="Lifecycle")
        )
        deleted = delete_dashboard(
            session,
            principal=principal,
            dashboard_id=created.id,
            expected_revision=1,
        )
    with session_factory() as session:
        trash = list_dashboards(
            session,
            principal=principal,
            offset=0,
            limit=50,
            status="deleted",
        )
    with session_factory() as session:
        restored = restore_dashboard(
            session,
            principal=principal,
            dashboard_id=created.id,
            expected_revision=2,
        )

    assert deleted.status == "deleted"
    assert trash.total == 1
    assert restored.status == "draft"
    assert restored.revision == 3


def test_dashboard_template_instance_copies_aggregate_with_new_logical_ids(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    with session_factory() as session:
        source = create_dashboard(
            session, principal=principal, request=CreateDashboard(name="Source")
        )
        source = save_dashboard_version(
            session,
            principal=principal,
            dashboard_id=source.id,
            request=aggregate_request(),
        )
        template = create_dashboard_template(
            session,
            principal=principal,
            request=CreateDashboardTemplate(
                name="Team template",
                source_dashboard_version_id=source.current_version_id,
                visibility="workspace",
            ),
        )
        instance = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(
                name="Instance",
                template_version_id=template.version_id,
            ),
        )

    assert instance.current_version == 1
    assert instance.pages[0].page_id != source.pages[0].page_id
    assert (
        instance.pages[0].components[0].component_id != source.pages[0].components[0].component_id
    )
