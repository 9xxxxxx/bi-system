import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from bi_system.core.config import get_settings
from bi_system.db.session import create_database_engine
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


def test_database_is_at_current_migration_head() -> None:
    if "BI_DATABASE_URL" not in os.environ:
        pytest.skip("BI_DATABASE_URL is required for migration state checks")

    get_settings.cache_clear()
    engine = create_database_engine(get_settings().database_url)

    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
            current_revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

    head_revision = ScriptDirectory.from_config(alembic_config()).get_current_head()

    assert current_revision == "0001_baseline"
    assert current_revision == head_revision
