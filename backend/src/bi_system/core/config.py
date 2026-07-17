from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./data/bi_system.db"
DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
DEFAULT_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BI System API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = DEFAULT_DATABASE_URL
    workspace_id: UUID = DEFAULT_WORKSPACE_ID
    storage_root: Path = Path("data/uploads")
    upload_max_bytes: Annotated[int, Field(gt=0)] = 100 * 1024 * 1024
    xlsx_max_uncompressed_bytes: Annotated[int, Field(gt=0)] = 1024 * 1024 * 1024
    xlsx_max_compression_ratio: Annotated[float, Field(gt=1)] = 200.0
    import_max_rows: Annotated[int, Field(gt=0)] = 1_000_000
    import_chunk_rows: Annotated[int, Field(gt=0)] = 2_000
    preview_max_rows: Annotated[int, Field(gt=0)] = 100
    import_issue_sample_limit: Annotated[int, Field(gt=0)] = 1_000
    import_worker_lease_seconds: Annotated[int, Field(gt=0)] = 120
    query_timeout_seconds: Annotated[int, Field(ge=1, le=60)] = 10
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: DEFAULT_CORS_ORIGINS.copy(),
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def validate_production_cors(self) -> "Settings":
        if "*" in self.cors_origins:
            msg = "CORS wildcard origins are not allowed"
            raise ValueError(msg)

        if self.environment == "production" and self.cors_origins == DEFAULT_CORS_ORIGINS:
            msg = "BI_CORS_ORIGINS must be set explicitly in production"
            raise ValueError(msg)

        return self

    @model_validator(mode="after")
    def validate_ingestion_limits(self) -> "Settings":
        if self.preview_max_rows > self.import_chunk_rows:
            msg = "BI_PREVIEW_MAX_ROWS must not exceed BI_IMPORT_CHUNK_ROWS"
            raise ValueError(msg)
        if self.import_chunk_rows > self.import_max_rows:
            msg = "BI_IMPORT_CHUNK_ROWS must not exceed BI_IMPORT_MAX_ROWS"
            raise ValueError(msg)
        if self.xlsx_max_uncompressed_bytes < self.upload_max_bytes:
            msg = "BI_XLSX_MAX_UNCOMPRESSED_BYTES must not be less than BI_UPLOAD_MAX_BYTES"
            raise ValueError(msg)

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
