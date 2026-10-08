"""Explicit opt-in provider configuration. No HTTP calls when keys are absent."""

import os
from dataclasses import dataclass

from apps.api.connectors.factcheck import GoogleFactCheckConnector
from apps.api.connectors.http_client import ProviderHttpClient
from apps.api.connectors.newsapi import NewsApiConnector


@dataclass(frozen=True, slots=True)
class ConnectorConfiguration:
    newsapi_key: str | None = None
    google_factcheck_key: str | None = None

    @classmethod
    def from_environment(cls) -> "ConnectorConfiguration":
        return cls(
            newsapi_key=os.environ.get("NEWSAPI_KEY") or None,
            google_factcheck_key=os.environ.get("GOOGLE_FACTCHECK_API_KEY") or None,
        )

    def enabled_providers(self) -> tuple[str, ...]:
        providers: list[str] = []
        if self.newsapi_key and self.newsapi_key.strip():
            providers.append("newsapi")
        if self.google_factcheck_key and self.google_factcheck_key.strip():
            providers.append("google_factcheck")
        return tuple(providers)


def build_connectors(
    http: ProviderHttpClient, config: ConnectorConfiguration
) -> tuple[NewsApiConnector | GoogleFactCheckConnector, ...]:
    connectors: list[NewsApiConnector | GoogleFactCheckConnector] = []
    if config.newsapi_key and config.newsapi_key.strip():
        connectors.append(NewsApiConnector(http, api_key=config.newsapi_key))
    if config.google_factcheck_key and config.google_factcheck_key.strip():
        connectors.append(GoogleFactCheckConnector(http, api_key=config.google_factcheck_key))
    return tuple(connectors)
