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

__all__ = [
    "ContentKind",
    "DiscoveryRequest",
    "DiscoveryResult",
    "ExternalDiscoveryHit",
    "GoogleFactCheckConnector",
    "NewsApiConnector",
    "Provider",
]
