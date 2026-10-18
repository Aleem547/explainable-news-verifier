"""Phase 9B external provider connectors (no automatic live requests)."""

from apps.api.connectors.contracts import (
    ContentKind,
    DiscoveryRequest,
    DiscoveryResult,
    ExternalDiscoveryHit,
    Provider,
)
from apps.api.connectors.factcheck import GoogleFactCheckConnector
from apps.api.connectors.newsapi import NewsApiConnector
from apps.api.connectors.gdelt import GdeltDocConnector
from apps.api.connectors.rss import RssFeedConnector

__all__ = [
    "ContentKind",
    "DiscoveryRequest",
    "DiscoveryResult",
    "ExternalDiscoveryHit",
    "GoogleFactCheckConnector",
    "GdeltDocConnector",
    "RssFeedConnector",
    "NewsApiConnector",
    "Provider",
]
