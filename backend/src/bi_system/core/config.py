from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./data/bi_system.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BI System API"
    environment: str = "local"
    api_prefix: str = "/api/v1"
    database_url: str = DEFAULT_DATABASE_URL
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
