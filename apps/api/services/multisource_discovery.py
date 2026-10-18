"""Restricted provider discovery: metadata only; never claim-level evidence.

`both` preserves its legacy meaning (NewsAPI and Google Fact Check). A caller
can explicitly select `gdelt` for the free, credential-less DOC API. Neither
provider class nor this service fetches external article bodies.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.connectors.contracts import DiscoveryRequest
from apps.api.connectors.factcheck import GoogleFactCheckConnector
from apps.api.connectors.gdelt import GdeltDocConnector
from apps.api.connectors.fallback import discover_gdelt_or_rss
from apps.api.connectors.rss import RssFeedConnector
from apps.api.connectors.http_client import ConnectorError, ProviderHttpClient
from apps.api.connectors.newsapi import NewsApiConnector
from apps.api.connectors.registry import ConnectorConfiguration, build_connectors
from apps.api.schemas.multisource import ExternalDiscoveryRequest, ExternalDiscoveryResponse
from apps.api.services.external_ingestion import ingest_discovery_result


class NoConfiguredProviderError(RuntimeError):
    """No eligible provider for the requested discovery mode."""


class DiscoveryProvidersFailedError(RuntimeError):
    """Providers were eligible but all requests failed."""


async def discover_external_metadata(
    session: AsyncSession,
    request: ExternalDiscoveryRequest,
    http: ProviderHttpClient,
    config: ConnectorConfiguration,
) -> ExternalDiscoveryResponse:
    providers: list[tuple[str, NewsApiConnector | GoogleFactCheckConnector | GdeltDocConnector | RssFeedConnector]] = []
    if request.provider in {"gdelt", "gdelt_rss"}:
        providers.append(("gdelt_doc", GdeltDocConnector(http)))
    elif request.provider == "rss":
        providers.append(("rss_feed", RssFeedConnector(http)))
    else:
        for connector in build_connectors(http, config):
            name = "newsapi" if isinstance(connector, NewsApiConnector) else "google_factcheck"
            if request.provider in ("both", name):
                providers.append((name, connector))
    if not providers:
        raise NoConfiguredProviderError("No discovery provider enabled for this selection")

    succeeded: list[str] = []
    failed: list[str] = []
    count = 0
    documents = 0
    lookup = DiscoveryRequest(query=request.query, limit=request.limit)
    for name, connector in providers:
        try:
            if request.provider == "gdelt_rss" and name == "gdelt_doc":
                result, did_fallback = await discover_gdelt_or_rss(http, lookup)
                if did_fallback:
                    failed.append("gdelt_doc")
                    name = "rss_feed"
            else:
                result = await connector.search(lookup)
        except ConnectorError:
            failed.append(name)
            continue
        ingestion = await ingest_discovery_result(session, result)
        succeeded.append(name)
        count += len(result.hits)
        documents += ingestion.documents_seen
    if not succeeded:
        raise DiscoveryProvidersFailedError("Every attempted provider failed")
    return ExternalDiscoveryResponse(
        searched_providers=succeeded,
        failed_providers=failed,
        discovered_hits=count,
        documents_seen=documents,
    )
