import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from bi_system.db.session import create_database_engine
from sqlalchemy import inspect

pytest.importorskip(
    "bi_system.db.models.dashboards",
    reason="M3-R1 dashboard models and migration are not available yet",
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_TABLES = {
    "dashboards",
    "dashboard_versions",
    "dashboard_pages",
    "dashboard_components",
    "dashboard_layouts",
    "dashboard_templates",
    "dashboard_template_versions",
    "dashboard_permissions",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _table_names(database_url: str) -> set[str]:
    engine = create_database_engine(database_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_dashboard_migration_upgrades_downgrades_and_reupgrades(tmp_path: Path) -> None:
    database_url = os.environ.get(
        "BI_DATABASE_URL",
        f"sqlite+pysqlite:///{(tmp_path / 'dashboard-migration.db').as_posix()}",
    )
    config = _alembic_config(database_url)
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    assert head is not None
    head_script = scripts.get_revision(head)
    assert head_script is not None
    previous = head_script.down_revision
    assert isinstance(previous, str)

    command.upgrade(config, "head")
    assert _table_names(database_url) >= DASHBOARD_TABLES

    command.downgrade(config, previous)
    assert DASHBOARD_TABLES.isdisjoint(_table_names(database_url))

    command.upgrade(config, "head")
    assert _table_names(database_url) >= DASHBOARD_TABLES
