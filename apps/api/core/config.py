from functools import lru_cache

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
