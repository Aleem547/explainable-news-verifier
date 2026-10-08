"""NewsAPI Everything article *discovery*, not full-text retrieval."""

from datetime import UTC, datetime
from typing import Any

from apps.api.connectors.contracts import (
    ContentKind,
    DiscoveryRequest,
    DiscoveryResult,
    ExternalDiscoveryHit,
    Provider,
)
from apps.api.connectors.http_client import ConnectorError, ProviderHttpClient
from apps.api.connectors.normalization import article_identity, string_value, timestamp

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"


class NewsApiConnector:
    def __init__(self, http: ProviderHttpClient, *, api_key: str):
        if not api_key.strip():
            raise ValueError("NewsAPI key is required for live requests.")
        self._http = http
        self._api_key = api_key.strip()

    async def search(self, request: DiscoveryRequest) -> DiscoveryResult:
        data = await self._http.get_json(
            provider=Provider.NEWSAPI,
            endpoint=NEWSAPI_ENDPOINT,
            parameters={
                "q": request.query.strip(),
                "pageSize": request.limit,
                "sortBy": "relevancy",
                "language": request.language.lower(),
            },
            headers={"X-Api-Key": self._api_key},
        )
        if data.get("status") != "ok" or not isinstance(data.get("articles"), list):
            raise ConnectorError(Provider.NEWSAPI, "provider_returned_error")
        now = datetime.now(UTC)
        hits: list[ExternalDiscoveryHit] = []
        seen: set[str] = set()
        for item in data["articles"][: request.limit]:
            if not isinstance(item, dict):
                continue
            identity = article_identity(item.get("url"))
            title = string_value(item.get("title"))
            if identity is None or title is None or identity[0] in seen:
                continue
            seen.add(identity[0])
            source: Any = item.get("source")
            if not isinstance(source, dict):
                source = {}
            publisher = string_value(source.get("name"), limit=255) or identity[1]
            hits.append(
                ExternalDiscoveryHit(
                    provider=Provider.NEWSAPI,
                    kind=ContentKind.NEWS_ARTICLE,
                    url=identity[0],
                    publisher_domain=identity[1],
                    publisher_name=publisher,
                    title=title,
                    snippet=string_value(item.get("description"), limit=2000),
                    discovered_at=now,
                    published_at=timestamp(item.get("publishedAt")),
                    language=request.language.lower(),
                )
            )
        count = data.get("totalResults")
        return DiscoveryResult(
            provider=Provider.NEWSAPI,
            query=request.query,
            hits=tuple(hits),
            reported_total=count if type(count) is int and count >= 0 else None,
        )
