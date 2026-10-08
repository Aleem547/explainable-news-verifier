"""Bounded HTTP JSON discovery against an exact allowlist of provider API URLs.

No arbitrary article URL is fetched, and redirects are refused. A mocked
httpx.AsyncClient can be injected for entirely offline unit testing.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

_ALLOWED_ENDPOINTS = frozenset(
    {
        "https://newsapi.org/v2/everything",
        "https://factchecktools.googleapis.com/v1alpha1/claims:search",
    }
)
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class ConnectorError(RuntimeError):
    """Sanitized error. Do not expose URL/query/API keys/provider response bodies."""

    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")


@dataclass(frozen=True, slots=True)
class HttpPolicy:
    max_attempts: int = 3
    max_bytes: int = 1_000_000
    backoff_seconds: float = 0.2
    max_retry_after_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if not 1000 <= self.max_bytes <= 5_000_000:
            raise ValueError("max_bytes outside safe bounds")
        if not 0 <= self.backoff_seconds <= 10:
            raise ValueError("invalid backoff_seconds")
        if not 0 <= self.max_retry_after_seconds <= 30:
            raise ValueError("invalid max_retry_after_seconds")


class ProviderHttpClient:
    def __init__(self, client: httpx.AsyncClient, policy: HttpPolicy | None = None):
        self.client = client
        self.policy = policy or HttpPolicy()

    async def get_json(
        self,
        *,
        provider: str,
        endpoint: str,
        parameters: dict[str, str | int],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        if endpoint not in _ALLOWED_ENDPOINTS:
            raise ValueError("Provider API endpoint is not allowlisted.")
        for attempt in range(self.policy.max_attempts):
            try:
                # Streaming places a strict bound on bytes retained in memory.
                async with self.client.stream(
                    "GET", endpoint, params=parameters, headers=headers, follow_redirects=False
                ) as response:
                    status = response.status_code
                    if status in _RETRYABLE_STATUS:
                        if attempt + 1 >= self.policy.max_attempts:
                            raise ConnectorError(provider, f"retry_exhausted_http_{status}")
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = float(retry_after) if retry_after is not None else None
                        except ValueError:
                            delay = None
                        if delay is None or delay < 0:
                            delay = self.policy.backoff_seconds * (2**attempt)
                        if delay > self.policy.max_retry_after_seconds:
                            raise ConnectorError(provider, "rate_limit_wait_exceeds_budget")
                    elif 300 <= status <= 399:
                        raise ConnectorError(provider, "redirect_refused")
                    elif status >= 400:
                        raise ConnectorError(provider, f"http_{status}")
                    else:
                        pieces: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.policy.max_bytes:
                                raise ConnectorError(provider, "payload_too_large")
                            pieces.append(chunk)
                        try:
                            data = json.loads(b"".join(pieces))
                        except (ValueError, UnicodeError):
                            raise ConnectorError(provider, "invalid_json") from None
                        if not isinstance(data, dict):
                            raise ConnectorError(provider, "invalid_response_structure")
                        return data
            except httpx.RequestError:
                if attempt + 1 >= self.policy.max_attempts:
                    raise ConnectorError(provider, "network_error") from None
                delay = self.policy.backoff_seconds * (2**attempt)
            await asyncio.sleep(delay)
        raise ConnectorError(provider, "retry_exhausted")


def new_provider_http_client() -> httpx.AsyncClient:
    """Use no ambient HTTP proxy by default, disable redirects and bound timeout."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=False,
        trust_env=False,
        headers={"Accept": "application/json", "User-Agent": "ExplainableNewsVerifier/0.1"},
    )
