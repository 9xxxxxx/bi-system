import pytest
from bi_system.core.config import Settings


def test_settings_default_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BI_DATABASE_URL", raising=False)

    settings = Settings()

    assert settings.api_prefix == "/api/v1"
    assert settings.database_url.startswith("sqlite+pysqlite:///")
    assert settings.storage_root.as_posix() == "data/uploads"
    assert settings.upload_max_bytes == 100 * 1024 * 1024
    assert settings.import_max_rows == 1_000_000
    assert settings.import_chunk_rows == 2_000
    assert settings.preview_max_rows == 100


def test_settings_reject_invalid_ingestion_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BI_IMPORT_CHUNK_ROWS", "50")
    monkeypatch.setenv("BI_PREVIEW_MAX_ROWS", "100")

    with pytest.raises(ValueError, match="BI_PREVIEW_MAX_ROWS"):
        Settings()
