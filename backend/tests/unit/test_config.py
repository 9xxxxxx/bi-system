import pytest
from bi_system.core.config import Settings


def test_settings_default_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BI_DATABASE_URL", raising=False)

    settings = Settings()

    assert settings.api_prefix == "/api/v1"
    assert settings.database_url.startswith("sqlite+pysqlite:///")
