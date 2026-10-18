"""GDELT -> RSS on transient discovery failures, never on invalid evidence.

Both providers return discovery metadata, not full-text or claim verdicts.
"""

from apps.api.connectors.contracts import DiscoveryRequest, DiscoveryResult
from apps.api.connectors.gdelt import GdeltDocConnector
from apps.api.connectors.http_client import ConnectorError, ProviderHttpClient
from apps.api.connectors.rss import RssFeedConnector

_TRANSIENT_GDELT_FAILURES = frozenset({
    "network_error", "retry_exhausted_http_429", "rate_limit_wait_exceeds_budget",
    "retry_exhausted_http_408", "retry_exhausted_http_500",
    "retry_exhausted_http_502", "retry_exhausted_http_503",
    "retry_exhausted_http_504",
})


async def discover_gdelt_or_rss(
    http: ProviderHttpClient,
    request: DiscoveryRequest,
) -> tuple[DiscoveryResult, bool]:
    """Return (discovery result, did_fallback).

    GDELT errors are not suppressed if they're schema/validation failures.
    """
    try:
        return await GdeltDocConnector(http).search(request), False
    except ConnectorError as exc:
        if exc.reason not in _TRANSIENT_GDELT_FAILURES:
            raise
    return await RssFeedConnector(http).search(request), True
