from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bi_system.dashboards.service import (
    DashboardPurgeBlock,
    DashboardPurgeResult,
    purge_expired_dashboards,
)
from bi_system.db.base import Base
from bi_system.db.models.dashboards import (
    Dashboard,
    DashboardComponent,
    DashboardLayout,
    DashboardPage,
    DashboardPermission,
    DashboardTemplate,
    DashboardTemplateVersion,
    DashboardVersion,
)
from bi_system.db.models.identity import User
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from sqlalchemy import func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema


@dataclass(frozen=True, slots=True)
class PurgePortabilityContext:
    engine: Engine
    session_factory: sessionmaker[Session]
    workspace_id: UUID
    foreign_workspace_id: UUID
    owner_id: UUID
    foreign_owner_id: UUID


@dataclass(frozen=True, slots=True)
class StoredDashboard:
    dashboard_id: UUID
    version_id: UUID
    page_id: UUID | None = None
    component_id: UUID | None = None
    layout_id: UUID | None = None
    permission_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class StoredTemplateReference:
    template_id: UUID
    template_version_id: UUID


@pytest.fixture
def purge_context(tmp_path: Path) -> Iterator[PurgePortabilityContext]:
    database_url = os.environ.get(
        "BI_DATABASE_URL",
        f"sqlite+pysqlite:///{(tmp_path / 'dashboard-purge-portability.db').as_posix()}",
    )
    with portable_database_engine(database_url) as engine:
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        workspace_id = uuid4()
        foreign_workspace_id = uuid4()
        with session_factory.begin() as session:
            owner = User(
                workspace_id=workspace_id,
                username=f"purge-owner-{uuid4().hex}",
                display_name="Purge portability owner",
                password_hash="not-used",
                must_change_password=False,
            )
            foreign_owner = User(
                workspace_id=foreign_workspace_id,
                username=f"purge-foreign-{uuid4().hex}",
                display_name="Foreign purge owner",
                password_hash="not-used",
                must_change_password=False,
            )
            session.add_all([owner, foreign_owner])
            session.flush()
            context = PurgePortabilityContext(
                engine=engine,
                session_factory=session_factory,
                workspace_id=workspace_id,
                foreign_workspace_id=foreign_workspace_id,
                owner_id=owner.id,
                foreign_owner_id=foreign_owner.id,
            )
        yield context


def test_dashboard_purge_is_portable_bounded_and_idempotent(
    purge_context: PurgePortabilityContext,
) -> None:
    context = purge_context
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    oldest_id = UUID(int=101)
    blocked_id = UUID(int=102)
    cutoff_low_id = UUID(int=103)
    cutoff_high_id = UUID(int=104)
    within_window_id = UUID(int=105)
    foreign_id = UUID(int=201)

    with context.session_factory.begin() as session:
        oldest = _add_deleted_dashboard(
            session,
            context=context,
            dashboard_id=oldest_id,
            deleted_at=now - timedelta(days=40),
            with_dependents=True,
        )
        blocked = _add_deleted_dashboard(
            session,
            context=context,
            dashboard_id=blocked_id,
            deleted_at=now - timedelta(days=35),
        )
        template_reference = _add_template_reference(
            session,
            context=context,
            source_version_id=blocked.version_id,
        )
        _add_deleted_dashboard(
            session,
            context=context,
            dashboard_id=cutoff_low_id,
            deleted_at=now - timedelta(days=30),
        )
        _add_deleted_dashboard(
            session,
            context=context,
            dashboard_id=cutoff_high_id,
            deleted_at=now - timedelta(days=30),
        )
        _add_deleted_dashboard(
            session,
            context=context,
            dashboard_id=within_window_id,
            deleted_at=now - timedelta(days=30) + timedelta(microseconds=1),
        )
        _add_deleted_dashboard(
            session,
            context=context,
            dashboard_id=foreign_id,
            deleted_at=now - timedelta(days=50),
            foreign_workspace=True,
        )

    administrator = QueryPrincipal(
        user_id=context.owner_id,
        workspace_id=context.workspace_id,
        is_system_admin=True,
    )
    with context.session_factory() as session:
        preview = purge_expired_dashboards(
            session,
            principal=administrator,
            now=now,
            limit=3,
            dry_run=True,
        )

    assert isinstance(preview, DashboardPurgeResult)
    assert preview.cutoff == now - timedelta(days=30)
    assert preview.dry_run is True
    assert preview.candidate_ids == (oldest_id, blocked_id, cutoff_low_id)
    assert preview.eligible_ids == (oldest_id, cutoff_low_id)
    assert preview.purged_ids == ()
    _assert_blocked_reference(preview.blocked, blocked_id, template_reference)
    with context.session_factory() as session:
        assert session.get(Dashboard, oldest_id) is not None
        assert session.get(Dashboard, cutoff_low_id) is not None

    with context.session_factory() as session:
        result = purge_expired_dashboards(
            session,
            principal=administrator,
            now=now,
            limit=100,
        )

    assert isinstance(result, DashboardPurgeResult)
    assert result.cutoff == now - timedelta(days=30)
    assert result.dry_run is False
    assert result.candidate_ids == (oldest_id, blocked_id, cutoff_low_id, cutoff_high_id)
    assert result.eligible_ids == (oldest_id, cutoff_low_id, cutoff_high_id)
    assert result.purged_ids == (oldest_id, cutoff_low_id, cutoff_high_id)
    _assert_blocked_reference(result.blocked, blocked_id, template_reference)

    with context.session_factory() as session:
        assert session.get(Dashboard, oldest_id) is None
        assert session.get(Dashboard, cutoff_low_id) is None
        assert session.get(Dashboard, cutoff_high_id) is None
        assert session.get(Dashboard, blocked_id) is not None
        assert session.get(Dashboard, within_window_id) is not None
        assert session.get(Dashboard, foreign_id) is not None
        assert (
            session.get(DashboardTemplateVersion, template_reference.template_version_id)
            is not None
        )
        _assert_dashboard_dependents_removed(session, oldest)

    with context.session_factory() as session:
        repeated = purge_expired_dashboards(
            session,
            principal=administrator,
            now=now,
            limit=100,
        )

    assert repeated.candidate_ids == (blocked_id,)
    assert repeated.eligible_ids == ()
    assert repeated.purged_ids == ()
    _assert_blocked_reference(repeated.blocked, blocked_id, template_reference)


def _add_deleted_dashboard(
    session: Session,
    *,
    context: PurgePortabilityContext,
    dashboard_id: UUID,
    deleted_at: datetime,
    with_dependents: bool = False,
    foreign_workspace: bool = False,
) -> StoredDashboard:
    workspace_id = context.foreign_workspace_id if foreign_workspace else context.workspace_id
    owner_id = context.foreign_owner_id if foreign_workspace else context.owner_id
    dashboard = Dashboard(
        id=dashboard_id,
        workspace_id=workspace_id,
        owner_user_id=owner_id,
        name=f"Purge candidate {dashboard_id}",
        status="deleted",
        revision=2,
        current_version=1,
        deleted_at=deleted_at,
    )
    version = DashboardVersion(
        dashboard_id=dashboard.id,
        version=1,
        status="draft",
        created_by_user_id=owner_id,
    )
    session.add_all([dashboard, version])
    session.flush()
    if not with_dependents:
        return StoredDashboard(dashboard_id=dashboard.id, version_id=version.id)

    page = DashboardPage(
        dashboard_version_id=version.id,
        page_id=uuid4(),
        title="Cascade evidence",
        ordinal=0,
    )
    session.add(page)
    session.flush()
    component = DashboardComponent(
        dashboard_version_id=version.id,
        component_id=uuid4(),
        page_row_id=page.id,
        component_type="kpi",
        config_schema_version=1,
        config={"schema_version": 1, "title": "Cascade"},
        ordinal=0,
    )
    layout = DashboardLayout(
        dashboard_version_id=version.id,
        schema_version=1,
        profile="desktop",
        columns=12,
        row_height=8,
        items=[],
    )
    permission = DashboardPermission(
        dashboard_id=dashboard.id,
        subject_type="user",
        subject_id=owner_id,
        capability="view",
        created_by_user_id=owner_id,
    )
    session.add_all([component, layout, permission])
    session.flush()
    return StoredDashboard(
        dashboard_id=dashboard.id,
        version_id=version.id,
        page_id=page.id,
        component_id=component.id,
        layout_id=layout.id,
        permission_id=permission.id,
    )


def _add_template_reference(
    session: Session,
    *,
    context: PurgePortabilityContext,
    source_version_id: UUID,
) -> StoredTemplateReference:
    template = DashboardTemplate(
        workspace_id=context.workspace_id,
        owner_user_id=context.owner_id,
        name="Blocked purge template",
        status="published",
        visibility="workspace",
        revision=1,
        current_version=1,
    )
    session.add(template)
    session.flush()
    version = DashboardTemplateVersion(
        template_id=template.id,
        version=1,
        source_dashboard_version_id=source_version_id,
        created_by_user_id=context.owner_id,
    )
    session.add(version)
    session.flush()
    return StoredTemplateReference(
        template_id=template.id,
        template_version_id=version.id,
    )


def _assert_blocked_reference(
    blocked: tuple[DashboardPurgeBlock, ...],
    dashboard_id: UUID,
    expected: StoredTemplateReference,
) -> None:
    assert len(blocked) == 1
    block = blocked[0]
    assert isinstance(block, DashboardPurgeBlock)
    assert block.dashboard_id == dashboard_id
    assert len(block.references) == 1
    reference = block.references[0]
    assert reference.template_id == expected.template_id
    assert reference.template_name == "Blocked purge template"
    assert reference.template_version_id == expected.template_version_id
    assert reference.version == 1


def _assert_dashboard_dependents_removed(session: Session, stored: StoredDashboard) -> None:
    assert session.get(DashboardVersion, stored.version_id) is None
    assert stored.page_id is not None
    assert stored.component_id is not None
    assert stored.layout_id is not None
    assert stored.permission_id is not None
    assert session.get(DashboardPage, stored.page_id) is None
    assert session.get(DashboardComponent, stored.component_id) is None
    assert session.get(DashboardLayout, stored.layout_id) is None
    assert session.get(DashboardPermission, stored.permission_id) is None
    assert (
        session.scalar(
            select(func.count(DashboardVersion.id)).where(
                DashboardVersion.dashboard_id == stored.dashboard_id
            )
        )
        == 0
    )


@contextmanager
def portable_database_engine(database_url: str) -> Generator[Engine]:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        engine = create_database_engine(database_url)
        try:
            yield engine
        finally:
            engine.dispose()
        return

    schema_name = f"bi_m3_purge_test_{uuid4().hex}"
    administration_engine = create_database_engine(database_url)
    schema_created = False
    try:
        with administration_engine.begin() as connection:
            connection.execute(CreateSchema(schema_name))
        schema_created = True
        isolated_url = url.update_query_dict({"options": f"-csearch_path={schema_name}"})
        engine = create_database_engine(isolated_url.render_as_string(hide_password=False))
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        if schema_created:
            with administration_engine.begin() as connection:
                connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))
        administration_engine.dispose()
