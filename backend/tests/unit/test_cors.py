import pytest
from bi_system.core.config import Settings
from pydantic import ValidationError


def test_development_cors_defaults_to_vite_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BI_ENVIRONMENT", raising=False)
    monkeypatch.delenv("BI_CORS_ORIGINS", raising=False)

    settings = Settings()

    assert settings.environment == "development"
    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_origins_can_be_loaded_from_comma_separated_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BI_CORS_ORIGINS", "https://bi.example.com, https://reports.example.com")

    settings = Settings()

    assert settings.cors_origins == ["https://bi.example.com", "https://reports.example.com"]


def test_production_requires_explicit_non_local_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BI_ENVIRONMENT", "production")
    monkeypatch.delenv("BI_CORS_ORIGINS", raising=False)

    with pytest.raises(ValidationError, match="BI_CORS_ORIGINS"):
        Settings()


def test_production_rejects_wildcard_cors_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BI_ENVIRONMENT", "production")
    monkeypatch.setenv("BI_CORS_ORIGINS", "*")

    with pytest.raises(ValidationError, match="wildcard"):
        Settings()
