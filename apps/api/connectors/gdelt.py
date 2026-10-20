"""Free GDELT DOC discovery connector — metadata, NEVER article evidence.

The HTTP client accepts only a fixed provider endpoint and never follows
redirects. GDELT "seendate" is the time a URL was observed, NOT publication time.
"""

import json
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

from apps.api.connectors.contracts import (
    ContentKind,
    DiscoveryRequest,
    DiscoveryResult,
    ExternalDiscoveryHit,
    Provider,
)
from apps.api.connectors.http_client import ConnectorError, ProviderHttpClient
from apps.api.connectors.normalization import article_identity
from apps.api.services.gdelt_metadata import (
    DiscoveryFormatError,
    GDELT_DOC_URL,
    build_article_list_url,
    parse_article_list,
)


class GdeltDocConnector:
    def __init__(self, http: ProviderHttpClient, *, timespan: str = "1week"):
        if timespan not in {"1day", "1week", "1month"}:
            raise ValueError("Unsupported GDELT timespan")
        self._http = http
        self._timespan = timespan

    async def search(self, request: DiscoveryRequest) -> DiscoveryResult:
        # B.2 supports English-only discovery; never mislabel other languages.
        if request.language.lower() != "en":
            raise ValueError("The GDELT connector currently supports only English")
        url = build_article_list_url(
            request.query, limit=request.limit, timespan=self._timespan
        )
        # The builder's URL has one fixed origin and fixed path. It is not used
        # as the HTTP destination; only its validated query arguments are sent.
        params = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        data = await self._http.get_json(
            provider=Provider.GDELT_DOC.value,
            endpoint=GDELT_DOC_URL,
            parameters=params,
            headers={},
        )
        try:
            candidates = parse_article_list(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                limit=request.limit,
            )
        except DiscoveryFormatError as exc:
            raise ConnectorError(Provider.GDELT_DOC.value, "invalid_article_list") from exc
        now = datetime.now(UTC)
        seen: set[str] = set()
        hits: list[ExternalDiscoveryHit] = []
        for candidate in candidates:
            # Phase 13B.1 validation is metadata-only. Revalidate against our
            # existing persisted-document identity limits as well.
            identity = article_identity(candidate.url)
            if identity is None or identity[0] in seen:
                continue
            canonical_url, domain = identity
            if domain != candidate.publisher_domain:
                continue
            # GDELT returns language names such as "English", not ISO codes.
            if candidate.language and candidate.language.casefold() not in {"english", "en"}:
                continue
            seen.add(canonical_url)
            hits.append(
                ExternalDiscoveryHit(
                    provider=Provider.GDELT_DOC,
                    kind=ContentKind.NEWS_ARTICLE,
                    url=canonical_url,
                    publisher_domain=domain,
                    publisher_name=domain,
                    title=candidate.title,
                    snippet=None,  # No article body or provider snippet is promoted.
                    discovered_at=now,
                    published_at=None,  # GDELT seendate is NOT a publication date.
                    language="en" if candidate.language else None,
                )
            )
        return DiscoveryResult(
            provider=Provider.GDELT_DOC,
            query=request.query,
            hits=tuple(hits),
        )
