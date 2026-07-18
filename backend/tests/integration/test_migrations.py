import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from bi_system.core.config import get_settings
from bi_system.db.session import create_database_engine
from sqlalchemy import inspect, text

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
            table_names = set(inspect(connection).get_table_names())
    finally:
        engine.dispose()

    head_revision = ScriptDirectory.from_config(alembic_config()).get_current_head()

    assert current_revision == head_revision
    assert current_revision == "0005_dashboard_foundation"
    assert {
        "dashboard_components",
        "dashboard_layouts",
        "dashboard_pages",
        "dashboard_permissions",
        "dashboard_template_versions",
        "dashboard_templates",
        "dashboard_versions",
        "dashboards",
        "dataset_fields",
        "datasets",
        "file_blobs",
        "import_batches",
        "import_columns",
        "import_issue_samples",
        "import_targets",
        "import_templates",
        "metric_dimensions",
        "metrics",
        "quality_rules",
        "roles",
        "row_policies",
        "row_policy_assignments",
        "semantic_model_join_keys",
        "semantic_model_joins",
        "semantic_model_sources",
        "semantic_models",
        "source_files",
        "user_roles",
        "user_sessions",
        "users",
    } <= table_names
