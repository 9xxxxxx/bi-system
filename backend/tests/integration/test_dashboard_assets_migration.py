from pathlib import Path

from alembic import command
from alembic.config import Config
from bi_system.db.session import create_database_engine
from sqlalchemy import inspect

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _table_names(database_url: str) -> set[str]:
    engine = create_database_engine(database_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_dashboard_assets_migration_roundtrip_on_sqlite(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'dashboard-assets.db').as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("dashboard_assets")}
        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("dashboard_assets")
        }
        foreign_keys = {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_table"]
            for foreign_key in inspector.get_foreign_keys("dashboard_assets")
        }
    finally:
        engine.dispose()

    assert columns == {
        "id",
        "workspace_id",
        "blob_id",
        "uploaded_by_user_id",
        "original_name",
        "width",
        "height",
        "created_at",
    }
    assert "uq_dashboard_assets_workspace_blob" in unique_constraints
    assert foreign_keys[("blob_id",)] == "file_blobs"
    assert foreign_keys[("uploaded_by_user_id",)] == "users"

    command.downgrade(config, "0005_dashboard_foundation")
    assert "dashboard_assets" not in _table_names(database_url)

    command.upgrade(config, "head")
    assert "dashboard_assets" in _table_names(database_url)
