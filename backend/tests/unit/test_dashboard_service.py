from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bi_system.dashboards.contracts import (
    CreateDashboard,
    CreateDashboardTemplate,
    CreateDashboardTemplateVersion,
    InstantiateDashboardTemplate,
    ReplaceDashboardPermissions,
    SaveDashboardVersion,
)
from bi_system.dashboards.errors import (
    DashboardConfigurationError,
    DashboardConflictError,
    DashboardForbiddenError,
    DashboardNotFoundError,
    DashboardReferenceConflictError,
)
from bi_system.dashboards.service import (
    activate_dashboard,
    create_dashboard,
    create_dashboard_template,
    create_dashboard_template_version,
    delete_dashboard,
    get_dashboard,
    get_dashboard_template,
    instantiate_dashboard_template,
    list_dashboard_templates,
    list_dashboards,
    publish_dashboard_template,
    purge_expired_dashboards,
    replace_dashboard_permissions,
    restore_dashboard,
    save_dashboard_version,
)
from bi_system.db.base import Base
from bi_system.db.models.dashboards import Dashboard, DashboardTemplateVersion, DashboardVersion
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
                "dashboard_templates:publish",
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
        template = publish_dashboard_template(
            session,
            principal=principal,
            template_id=template.id,
            expected_revision=1,
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


def test_dashboard_activate_save_and_reactivate_archives_previous_active_version(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    with session_factory() as session:
        created = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Activation lifecycle"),
        )
        first_active = activate_dashboard(
            session,
            principal=principal,
            dashboard_id=created.id,
            expected_revision=1,
        )
        draft = save_dashboard_version(
            session,
            principal=principal,
            dashboard_id=created.id,
            request=aggregate_request(base_version=1, expected_revision=2),
        )
        second_active = activate_dashboard(
            session,
            principal=principal,
            dashboard_id=created.id,
            expected_revision=3,
        )
    with session_factory() as session:
        versions = list(
            session.scalars(
                select(DashboardVersion)
                .where(DashboardVersion.dashboard_id == created.id)
                .order_by(DashboardVersion.version)
            ).all()
        )

    assert first_active.status == "active"
    assert first_active.revision == 2
    assert draft.status == "draft"
    assert draft.current_version == 2
    assert second_active.status == "active"
    assert second_active.revision == 4
    assert [version.status for version in versions] == ["archived", "active"]


def test_template_source_rejects_deleted_and_cross_workspace_dashboards(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    foreign_principal = QueryPrincipal(
        user_id=resources.foreign_user_id,
        workspace_id=resources.foreign_workspace_id,
        permissions=frozenset({"dashboards:view", "dashboards:edit"}),
    )
    with session_factory() as session:
        foreign_source = create_dashboard(
            session,
            principal=foreign_principal,
            request=CreateDashboard(name="Foreign source"),
        )
        deleted_source = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Deleted source"),
        )
        delete_dashboard(
            session,
            principal=principal,
            dashboard_id=deleted_source.id,
            expected_revision=1,
        )
        for source_version_id in (
            foreign_source.current_version_id,
            deleted_source.current_version_id,
        ):
            with pytest.raises(DashboardNotFoundError) as hidden_source:
                create_dashboard_template(
                    session,
                    principal=principal,
                    request=CreateDashboardTemplate(
                        name="Invalid source",
                        source_dashboard_version_id=source_version_id,
                        visibility="workspace",
                    ),
                )
            assert hidden_source.value.code == "dashboard_version_not_found"


def test_template_publish_version_and_explicit_old_version_instantiation_are_isolated(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    with session_factory() as session:
        source = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Template source"),
        )
        source_v2 = save_dashboard_version(
            session,
            principal=principal,
            dashboard_id=source.id,
            request=aggregate_request(),
        )
        template = create_dashboard_template(
            session,
            principal=principal,
            request=CreateDashboardTemplate(
                name="Published template",
                source_dashboard_version_id=source_v2.current_version_id,
                visibility="workspace",
            ),
        )
        ordinary_editor = QueryPrincipal(
            user_id=resources.viewer_id,
            workspace_id=resources.workspace_id,
            permissions=frozenset({"dashboards:view", "dashboards:edit"}),
        )
        with session_factory() as visibility_session:
            assert (
                list_dashboard_templates(
                    visibility_session,
                    principal=ordinary_editor,
                    status="draft",
                ).total
                == 0
            )
        with session_factory() as visibility_session, pytest.raises(DashboardNotFoundError):
            get_dashboard_template(
                visibility_session,
                principal=ordinary_editor,
                template_id=template.id,
            )
        with pytest.raises(DashboardConflictError) as unpublished_v1:
            instantiate_dashboard_template(
                session,
                principal=ordinary_editor,
                template_id=template.id,
                request=InstantiateDashboardTemplate(
                    name="Unpublished V1",
                    template_version_id=template.version_id,
                ),
            )
        manager_without_publish = QueryPrincipal(
            user_id=resources.owner_id,
            workspace_id=resources.workspace_id,
            permissions=frozenset({"dashboards:edit", "dashboard_templates:manage"}),
        )
        with pytest.raises(DashboardForbiddenError) as publish_forbidden:
            publish_dashboard_template(
                session,
                principal=manager_without_publish,
                template_id=template.id,
                expected_revision=1,
            )
        published_v1 = publish_dashboard_template(
            session,
            principal=principal,
            template_id=template.id,
            expected_revision=1,
        )
        with pytest.raises(DashboardConflictError) as duplicate_publish:
            publish_dashboard_template(
                session,
                principal=principal,
                template_id=template.id,
                expected_revision=2,
            )
        with pytest.raises(DashboardNotFoundError) as mismatched_template:
            instantiate_dashboard_template(
                session,
                principal=principal,
                template_id=uuid4(),
                request=InstantiateDashboardTemplate(
                    name="Wrong template path",
                    template_version_id=published_v1.version_id,
                ),
            )
        instance_v1 = instantiate_dashboard_template(
            session,
            principal=principal,
            template_id=template.id,
            request=InstantiateDashboardTemplate(
                name="V1 instance",
                template_version_id=published_v1.version_id,
            ),
        )
        source_v3 = save_dashboard_version(
            session,
            principal=principal,
            dashboard_id=source.id,
            request=aggregate_request(base_version=2, expected_revision=2),
        )
        draft_v2 = create_dashboard_template_version(
            session,
            principal=principal,
            template_id=template.id,
            request=CreateDashboardTemplateVersion(
                source_dashboard_version_id=source_v3.current_version_id,
                expected_revision=2,
            ),
        )
        with pytest.raises(DashboardConflictError) as unpublished_v2:
            instantiate_dashboard_template(
                session,
                principal=ordinary_editor,
                template_id=template.id,
                request=InstantiateDashboardTemplate(
                    name="Unpublished V2",
                    template_version_id=draft_v2.version_id,
                ),
            )
        with pytest.raises(DashboardConflictError) as duplicate_draft:
            create_dashboard_template_version(
                session,
                principal=principal,
                template_id=template.id,
                request=CreateDashboardTemplateVersion(
                    source_dashboard_version_id=source_v3.current_version_id,
                    expected_revision=3,
                ),
            )
        with pytest.raises(DashboardConflictError) as stale_template:
            create_dashboard_template_version(
                session,
                principal=principal,
                template_id=template.id,
                request=CreateDashboardTemplateVersion(
                    source_dashboard_version_id=source_v3.current_version_id,
                    expected_revision=2,
                ),
            )
        old_version_instance = instantiate_dashboard_template(
            session,
            principal=ordinary_editor,
            template_id=template.id,
            request=InstantiateDashboardTemplate(
                name="Pinned V1 instance",
                template_version_id=published_v1.version_id,
            ),
        )
        published_v2 = publish_dashboard_template(
            session,
            principal=principal,
            template_id=template.id,
            expected_revision=3,
        )

    assert published_v1.status == "published"
    assert unpublished_v1.value.code == "dashboard_template_version_unpublished"
    assert publish_forbidden.value.code == "dashboard_template_publish_forbidden"
    assert duplicate_publish.value.code == "dashboard_template_publish_conflict"
    assert mismatched_template.value.code == "dashboard_template_version_not_found"
    assert draft_v2.status == "draft"
    assert unpublished_v2.value.code == "dashboard_template_version_unpublished"
    assert duplicate_draft.value.code == "dashboard_template_version_conflict"
    assert stale_template.value.code == "dashboard_template_revision_conflict"
    assert draft_v2.version_id != published_v1.version_id
    assert published_v2.status == "published"
    assert published_v2.revision == 4
    assert instance_v1.current_version == 1
    assert old_version_instance.current_version == 1
    assert old_version_instance.pages[0].components[0].config == (
        instance_v1.pages[0].components[0].config
    )
    with session_factory() as session:
        template_version_count = session.scalar(
            select(func.count(DashboardTemplateVersion.id)).where(
                DashboardTemplateVersion.template_id == template.id
            )
        )
    with session_factory() as session, pytest.raises(DashboardReferenceConflictError) as referenced:
        delete_dashboard(
            session,
            principal=principal,
            dashboard_id=source.id,
            expected_revision=3,
        )
    assert template_version_count == 2
    assert referenced.value.code == "dashboard_reference_conflict"
    assert len(referenced.value.references) == 2
    assert {reference.version for reference in referenced.value.references} == {1, 2}


def test_template_instantiation_rejects_unavailable_legacy_source(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    with session_factory() as session:
        source = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Legacy template source"),
        )
        template = create_dashboard_template(
            session,
            principal=principal,
            request=CreateDashboardTemplate(
                name="Legacy template",
                source_dashboard_version_id=source.current_version_id,
                visibility="workspace",
            ),
        )
        published = publish_dashboard_template(
            session,
            principal=principal,
            template_id=template.id,
            expected_revision=1,
        )
    with session_factory.begin() as session:
        dashboard = session.get(Dashboard, source.id)
        assert dashboard is not None
        dashboard.status = "deleted"
        dashboard.deleted_at = datetime.now(UTC)
    with session_factory() as session, pytest.raises(DashboardConfigurationError) as deleted:
        instantiate_dashboard_template(
            session,
            principal=principal,
            template_id=template.id,
            request=InstantiateDashboardTemplate(
                name="Deleted source instance",
                template_version_id=published.version_id,
            ),
        )
    assert deleted.value.code == "dashboard_template_source_unavailable"

    with session_factory.begin() as session:
        dashboard = session.get(Dashboard, source.id)
        assert dashboard is not None
        dashboard.status = "draft"
        dashboard.deleted_at = None
        dashboard.workspace_id = resources.foreign_workspace_id
    with session_factory() as session, pytest.raises(DashboardConfigurationError) as foreign:
        instantiate_dashboard_template(
            session,
            principal=principal,
            template_id=template.id,
            request=InstantiateDashboardTemplate(
                name="Foreign source instance",
                template_version_id=published.version_id,
            ),
        )
    assert foreign.value.code == "dashboard_template_source_unavailable"


def test_restore_expires_after_thirty_days(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    now = datetime(2026, 7, 19, tzinfo=UTC)
    with session_factory() as session:
        created = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Expired trash"),
        )
        delete_dashboard(
            session,
            principal=principal,
            dashboard_id=created.id,
            expected_revision=1,
        )
        within_window = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Restorable trash"),
        )
        delete_dashboard(
            session,
            principal=principal,
            dashboard_id=within_window.id,
            expected_revision=1,
        )
    with session_factory.begin() as session:
        dashboard = session.get(Dashboard, created.id)
        restorable_dashboard = session.get(Dashboard, within_window.id)
        assert dashboard is not None
        assert restorable_dashboard is not None
        dashboard.deleted_at = now - timedelta(days=30)
        restorable_dashboard.deleted_at = now - timedelta(days=30) + timedelta(microseconds=1)

    with session_factory() as session, pytest.raises(DashboardConflictError) as expired:
        restore_dashboard(
            session,
            principal=principal,
            dashboard_id=created.id,
            expected_revision=2,
            now=now,
        )
    assert expired.value.code == "dashboard_restore_expired"

    with session_factory() as session:
        restored = restore_dashboard(
            session,
            principal=principal,
            dashboard_id=within_window.id,
            expected_revision=2,
            now=now,
        )
    assert restored.status == "draft"


@pytest.mark.parametrize("limit", [0, 1001])
def test_purge_rejects_invalid_limit(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
    limit: int,
) -> None:
    session_factory, resources, _engine = dashboard_store
    administrator = QueryPrincipal(
        user_id=resources.owner_id,
        workspace_id=resources.workspace_id,
        is_system_admin=True,
    )
    with session_factory() as session, pytest.raises(DashboardConfigurationError) as invalid:
        purge_expired_dashboards(
            session,
            principal=administrator,
            limit=limit,
        )

    assert invalid.value.code == "dashboard_purge_limit_invalid"


def test_purge_dry_run_respects_limit_without_deleting_candidates(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    administrator = QueryPrincipal(
        user_id=resources.owner_id,
        workspace_id=resources.workspace_id,
        is_system_admin=True,
    )
    now = datetime(2026, 7, 19, tzinfo=UTC)
    with session_factory() as session:
        dashboards = [
            create_dashboard(
                session,
                principal=principal,
                request=CreateDashboard(name=f"Dry-run candidate {index}"),
            )
            for index in range(3)
        ]
    with session_factory.begin() as session:
        for index, detail in enumerate(dashboards):
            dashboard = session.get(Dashboard, detail.id)
            assert dashboard is not None
            dashboard.status = "deleted"
            dashboard.deleted_at = now - timedelta(days=33 - index)

    with session_factory() as session:
        result = purge_expired_dashboards(
            session,
            principal=administrator,
            now=now,
            limit=2,
            dry_run=True,
        )

    assert result.cutoff == now - timedelta(days=30)
    assert result.dry_run is True
    assert result.candidate_ids == (dashboards[0].id, dashboards[1].id)
    assert result.eligible_ids == result.candidate_ids
    assert result.purged_ids == ()
    assert result.blocked == ()
    with session_factory() as session:
        assert all(session.get(Dashboard, detail.id) is not None for detail in dashboards)


def test_purge_skips_referenced_candidates_and_remains_idempotent(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    administrator = QueryPrincipal(
        user_id=resources.owner_id,
        workspace_id=resources.workspace_id,
        is_system_admin=True,
    )
    now = datetime(2026, 7, 19, tzinfo=UTC)
    with session_factory() as session:
        blocked_dashboard = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Referenced purge candidate"),
        )
        template = create_dashboard_template(
            session,
            principal=principal,
            request=CreateDashboardTemplate(
                name="Purge blocker",
                source_dashboard_version_id=blocked_dashboard.current_version_id,
                visibility="workspace",
            ),
        )
        safe_dashboard = create_dashboard(
            session,
            principal=principal,
            request=CreateDashboard(name="Safe purge candidate"),
        )
    with session_factory.begin() as session:
        blocked = session.get(Dashboard, blocked_dashboard.id)
        safe = session.get(Dashboard, safe_dashboard.id)
        assert blocked is not None
        assert safe is not None
        blocked.status = "deleted"
        blocked.deleted_at = now - timedelta(days=32)
        safe.status = "deleted"
        safe.deleted_at = now - timedelta(days=31)

    with session_factory() as session:
        result = purge_expired_dashboards(
            session,
            principal=administrator,
            now=now,
        )
    with session_factory() as session:
        repeated = purge_expired_dashboards(
            session,
            principal=administrator,
            now=now,
        )

    assert result.candidate_ids == (blocked_dashboard.id, safe_dashboard.id)
    assert result.eligible_ids == (safe_dashboard.id,)
    assert result.purged_ids == (safe_dashboard.id,)
    assert len(result.blocked) == 1
    assert result.blocked[0].dashboard_id == blocked_dashboard.id
    assert len(result.blocked[0].references) == 1
    assert result.blocked[0].references[0].template_id == template.id
    assert result.blocked[0].references[0].template_version_id == template.version_id
    assert repeated.candidate_ids == (blocked_dashboard.id,)
    assert repeated.eligible_ids == ()
    assert repeated.purged_ids == ()
    assert repeated.blocked == result.blocked
    with session_factory() as session:
        assert session.get(Dashboard, blocked_dashboard.id) is not None
        assert session.get(Dashboard, safe_dashboard.id) is None


def test_purge_requires_system_administrator(
    dashboard_store: tuple[sessionmaker[Session], DashboardResources, Engine],
) -> None:
    session_factory, resources, _engine = dashboard_store
    principal = owner_principal(resources)
    with session_factory() as session, pytest.raises(DashboardForbiddenError) as forbidden:
        purge_expired_dashboards(session, principal=principal)
    assert forbidden.value.code == "dashboard_purge_forbidden"

    unknown_administrator = QueryPrincipal(
        user_id=uuid4(),
        workspace_id=resources.workspace_id,
        is_system_admin=True,
    )
    with session_factory() as session, pytest.raises(DashboardNotFoundError) as missing_actor:
        purge_expired_dashboards(session, principal=unknown_administrator)
    assert missing_actor.value.code == "dashboard_actor_not_found"
