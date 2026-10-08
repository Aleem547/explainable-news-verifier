"""Live provider discovery adapter: metadata only, no article fetch or verification."""

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.connectors.contracts import DiscoveryRequest
from apps.api.connectors.http_client import ConnectorError, ProviderHttpClient
from apps.api.connectors.registry import ConnectorConfiguration, build_connectors
from apps.api.schemas.multisource import ExternalDiscoveryRequest, ExternalDiscoveryResponse
from apps.api.services.external_ingestion import ingest_discovery_result


class NoConfiguredProviderError(RuntimeError):
    """No requested provider has credentials configured."""


async def discover_external_metadata(
    session: AsyncSession,
    request: ExternalDiscoveryRequest,
    http: ProviderHttpClient,
    config: ConnectorConfiguration,
) -> ExternalDiscoveryResponse:
    providers = [
        item
        for item in build_connectors(http, config)
        if request.provider == "both"
        or item.__class__.__name__.lower().startswith(
            "newsapi" if request.provider == "newsapi" else "googlefactcheck"
        )
    ]
    if not providers:
        raise NoConfiguredProviderError("No credentials for the requested discovery providers")
    succeeded: list[str] = []
    failed: list[str] = []
    count = 0
    documents = 0
    for provider in providers:
        name = (
            "newsapi" if provider.__class__.__name__ == "NewsApiConnector" else "google_factcheck"
        )
        try:
            result = await provider.search(
                DiscoveryRequest(query=request.query, limit=request.limit)
            )
        except ConnectorError:
            failed.append(name)
            continue
        ingestion = await ingest_discovery_result(session, result)
        succeeded.append(name)
        count += len(result.hits)
        documents += ingestion.documents_seen
    if not succeeded:
        raise NoConfiguredProviderError("All configured discovery providers failed")
    return ExternalDiscoveryResponse(
        searched_providers=succeeded,
        failed_providers=failed,
        discovered_hits=count,
        documents_seen=documents,
    )
