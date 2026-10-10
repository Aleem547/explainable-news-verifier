from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Explainable News Verifier"
    app_version: str = "0.1.0"
    app_env: str = "development"
    debug: bool = False

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    database_url: str
    redis_url: str
    qdrant_url: str
    mlflow_tracking_uri: str

    # Never expose this server-to-server secret through NEXT_PUBLIC_* variables.
    # In staging/production the auth dependency fails closed when unset/short.
    internal_api_token: str = ""
    inference_requests_per_minute: int = Field(default=30, ge=1, le=10_000)
    inference_max_body_bytes: int = Field(default=16_384, ge=1024, le=65_536)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
