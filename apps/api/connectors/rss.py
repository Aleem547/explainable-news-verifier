"""Curated, free RSS discovery. Feed metadata is NOT independently verified evidence.

Never follows links or downloads article bodies. Feed destinations and their
article-host mappings are code-controlled and can be audited independently.
"""

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from apps.api.connectors.contracts import (
    ContentKind, DiscoveryRequest, DiscoveryResult, ExternalDiscoveryHit, Provider,
)
from apps.api.connectors.http_client import ConnectorError, ProviderHttpClient
from apps.api.connectors.normalization import article_identity


@dataclass(frozen=True, slots=True)
class RssFeed:
    url: str
    publisher: str
    allowed_domains: frozenset[str]


# Fixed destinations: no user-supplied RSS URLs or arbitrary outbound requests.
RSS_FEEDS: tuple[RssFeed, ...] = (
    RssFeed("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC News",
            frozenset({"bbc.com", "www.bbc.com", "bbc.co.uk", "www.bbc.co.uk"})),
    RssFeed("https://feeds.npr.org/1001/rss.xml", "NPR",
            frozenset({"npr.org", "www.npr.org"})),
    RssFeed("https://www.theguardian.com/world/rss", "The Guardian",
            frozenset({"theguardian.com", "www.theguardian.com"})),
)

_STOP = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "have", "will", "which",
    "what", "when", "where", "whose", "their", "were", "was", "are", "has", "does",
    "did", "into", "over", "under", "located", "according", "about", "news",
})


def _tokens(value: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]{3,}", value.casefold())
            if tok not in _STOP}


def _relevant(request: DiscoveryRequest, title: str, description: str) -> bool:
    important = _tokens(request.query)
    return bool(important and (important & _tokens(title + " " + description)))


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        date = parsedate_to_datetime(value)
    except (ValueError, TypeError, IndexError):
        return None
    if date.tzinfo is None or date.utcoffset() is None:
        return None
    return date.astimezone(UTC)


def parse_rss_items(payload: bytes, feed: RssFeed, request: DiscoveryRequest,
                    now: datetime) -> tuple[ExternalDiscoveryHit, ...]:
    """Parse bounded RSS 2.0; reject DTD/ENTITY and unknown publisher hosts."""
    if len(payload) > 512_000 or b"<!doctype" in payload.lower() or b"<!entity" in payload.lower():
        raise ConnectorError(Provider.RSS_FEED.value, "unsafe_xml")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        raise ConnectorError(Provider.RSS_FEED.value, "invalid_xml") from None
    if root.tag.lower() != "rss":
        raise ConnectorError(Provider.RSS_FEED.value, "unsupported_feed_format")
    channel = root.find("channel")
    if channel is None:
        raise ConnectorError(Provider.RSS_FEED.value, "invalid_feed_structure")
    found: list[ExternalDiscoveryHit] = []
    seen: set[str] = set()
    # Limit XML work even if the provider sends an extremely large item count.
    for entry in list(channel.findall("item"))[:150]:
        title = " ".join((entry.findtext("title") or "").split())[:500]
        raw_description = (entry.findtext("description") or "")[:2000]
        description = re.sub(r"<[^>]*>", " ", html.unescape(raw_description))
        if not title or not _relevant(request, title, description):
            continue
        identity = article_identity((entry.findtext("link") or "").strip())
        if identity is None:
            continue
        url, domain = identity
        if domain not in feed.allowed_domains or url in seen:
            continue
        seen.add(url)
        found.append(ExternalDiscoveryHit(
            provider=Provider.RSS_FEED,
            kind=ContentKind.NEWS_ARTICLE,
            url=url,
            publisher_domain=domain,
            publisher_name=feed.publisher,
            title=title,
            snippet=None,  # Do not persist teaser text as evidence.
            discovered_at=now,
            published_at=_published(entry.findtext("pubDate")),
            language="en",
        ))
        if len(found) >= request.limit:
            break
    return tuple(found)


class RssFeedConnector:
    def __init__(self, http: ProviderHttpClient):
        self._http = http

    async def search(self, request: DiscoveryRequest) -> DiscoveryResult:
        if request.language.lower() != "en":
            raise ValueError("RSS fallback currently supports English-only discovery")
        # 3 fixed destinations, at most one request to each, no HTTP redirects.
        async def fetch(feed: RssFeed):
            try:
                body = await self._http.get_feed_xml(
                    provider=Provider.RSS_FEED.value, endpoint=feed.url
                )
                return parse_rss_items(body, feed, request, datetime.now(UTC))
            except ConnectorError:
                return None

        batches = await asyncio.gather(*(fetch(feed) for feed in RSS_FEEDS))
        if all(batch is None for batch in batches):
            raise ConnectorError(Provider.RSS_FEED.value, "all_feeds_failed")
        unique: dict[str, ExternalDiscoveryHit] = {}
        for batch in batches:
            if batch is None:
                continue
            for hit in batch:
                unique.setdefault(hit.url, hit)
        return DiscoveryResult(
            provider=Provider.RSS_FEED,
            query=request.query,
            hits=tuple(list(unique.values())[:request.limit]),
        )
