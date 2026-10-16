
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application configuration
    app_name: str = "Explainable News Verifier"
    app_version: str = "0.1.0"
    app_env: str = "development"
    debug: bool = False

    # API configuration
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Infrastructure configuration
    database_url: str
    redis_url: str
    qdrant_url: str
    mlflow_tracking_uri: str

    # Internal API authentication
    # Never expose this server-to-server secret
    # through NEXT_PUBLIC_* variables.
    # Authentication must fail closed if the token
    # is missing or invalid.
    internal_api_token: str

    # API request limits
    inference_requests_per_minute: int = Field(
        default=30,
        ge=1,
        le=10000,
    )

    inference_user_requests_per_minute: int = Field(
        default=10,
        ge=1,
        le=10000,
    )

    inference_max_body_bytes: int = Field(
        default=16384,
        ge=1024,
        le=65536,
    )

    # Phase 12A: DuckDB resource configuration
    duckdb_threads: int = Field(
        default=2,
        ge=1,
        le=8,
    )

    duckdb_memory_limit_mb: int = Field(
        default=512,
        ge=128,
        le=2048,
    )

    duckdb_max_temp_directory_size_mb: int = Field(
        default=1024,
        ge=128,
        le=8192,
    )

    # Environment configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
