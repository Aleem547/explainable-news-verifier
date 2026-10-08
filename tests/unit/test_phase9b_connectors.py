"""Fully offline contract tests for Phase 9B connectors and HTTP guardrails."""

import json
from datetime import UTC

import httpx
import pytest

from apps.api.connectors.contracts import ContentKind, DiscoveryRequest, Provider
from apps.api.connectors.factcheck import GoogleFactCheckConnector
from apps.api.connectors.http_client import ConnectorError, HttpPolicy, ProviderHttpClient
from apps.api.connectors.newsapi import NewsApiConnector
from apps.api.connectors.normalization import article_identity, timestamp
from apps.api.connectors.registry import ConnectorConfiguration


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def news_result() -> dict[str, object]:
    return {
        "status": "ok",
        "totalResults": 2,
        "articles": [
            {
                "source": {"id": "site", "name": "Example Daily"},
                "title": "  Verified   story   ",
                "url": "https://example.org/story?utm=one#fragment",
                "description": "Report with details",
                "content": "[+200 chars] not a complete article",
                "publishedAt": "2026-10-08T12:30:00Z",
            },
            {
                "source": {"name": "Local News"},
                "title": "Another report",
                "url": "https://local.example.net/report",
                "description": "summary",
                "publishedAt": "invalid-date",
            },
        ],
    }


@pytest.mark.anyio
async def test_newsapi_search_preserves_provenance_and_avoids_fulltext(
    news_result: dict[str, object],
) -> None:
    captured: list[httpx.Request] = []

    def fake(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=news_result)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        connector = NewsApiConnector(ProviderHttpClient(client), api_key="private-key")
        result = await connector.search(DiscoveryRequest("some claim", limit=5))
    assert result.provider is Provider.NEWSAPI
    assert len(result.hits) == 2
    assert result.reported_total == 2
    assert result.hits[0].url == "https://example.org/story?utm=one"
    assert result.hits[0].publisher_domain == "example.org"
    assert result.hits[0].title == "Verified story"
    assert result.hits[0].snippet == "Report with details"
    assert result.hits[0].published_at is not None
    assert result.hits[0].published_at.tzinfo is UTC
    assert result.hits[1].published_at is None
    assert result.hits[0].kind is ContentKind.NEWS_ARTICLE
    assert "private-key" not in str(captured[0].url)
    assert captured[0].headers["x-api-key"] == "private-key"
    assert str(captured[0].url).startswith("https://newsapi.org/v2/everything")


@pytest.mark.anyio
async def test_factcheck_keeps_third_party_rating_separate() -> None:
    payload = {
        "claims": [
            {
                "text": "A claim about a new rule",
                "claimant": "A speaker",
                "claimDate": "2024-01-02T00:00:00Z",
                "claimReview": [
                    {
                        "publisher": {"name": "Factcheck Example", "site": "fact.example"},
                        "url": "https://fact.example/check-1",
                        "title": "Review of a claim",
                        "reviewDate": "2024-01-03T00:00:00Z",
                        "textualRating": "Mostly false",
                        "languageCode": "en",
                    }
                ],
            }
        ],
        "nextPageToken": "page-2",
    }
    captured: list[httpx.Request] = []

    def fake(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        connector = GoogleFactCheckConnector(ProviderHttpClient(client), api_key="google-secret")
        result = await connector.search(DiscoveryRequest("new rule"))
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.kind is ContentKind.FACT_CHECK_REVIEW
    assert hit.provider is Provider.GOOGLE_FACTCHECK
    assert hit.publisher_domain == "fact.example"
    assert hit.matched_claim == "A claim about a new rule"
    assert hit.claimant == "A speaker"
    assert hit.rating_text == "Mostly false"
    assert hit.published_at is not None
    assert hit.claim_date is not None
    assert result.next_page_token == "page-2"
    assert captured[0].headers["x-goog-api-key"] == "google-secret"
    assert "google-secret" not in str(captured[0].url)


@pytest.mark.anyio
async def test_invalid_or_duplicate_article_urls_are_skipped() -> None:
    payload = {
        "status": "ok",
        "articles": [
            {"url": "http://local.example/story", "title": "Plain HTTP"},
            {"url": "http://127.0.0.1:8000/private", "title": "Private"},
            {"url": "https://public.example/story#part", "title": "Normal"},
            {"url": "https://public.example/story#other", "title": "Duplicate"},
            {"url": "https://public.example/other", "title": None},
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        result = await NewsApiConnector(ProviderHttpClient(client), api_key="test").search(
            DiscoveryRequest("title")
        )
    assert len(result.hits) == 1
    assert result.hits[0].title == "Normal"


@pytest.mark.anyio
async def test_http_retries_after_429_without_leaking_key() -> None:
    calls = 0

    def fake(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"status": "ok", "articles": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        http = ProviderHttpClient(client, policy=HttpPolicy(backoff_seconds=0))
        await NewsApiConnector(http, api_key="never-log-me").search(DiscoveryRequest("hello"))
    assert calls == 2


@pytest.mark.anyio
async def test_large_retry_after_fails_fast() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "120"}))
    ) as client:
        connector = NewsApiConnector(ProviderHttpClient(client), api_key="hidden")
        with pytest.raises(ConnectorError, match="rate_limit_wait_exceeds_budget") as exc:
            await connector.search(DiscoveryRequest("hello"))
        assert "hidden" not in str(exc.value)


@pytest.mark.anyio
async def test_redirect_refused_with_no_second_request() -> None:
    requests = 0

    def fake(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        with pytest.raises(ConnectorError, match="redirect_refused"):
            await NewsApiConnector(ProviderHttpClient(client), api_key="test").search(
                DiscoveryRequest("hello")
            )
    assert requests == 1


@pytest.mark.anyio
async def test_response_size_is_bounded() -> None:
    huge = json.dumps({"articles": [{"content": "a" * 4000}]})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=huge))
    ) as client:
        http = ProviderHttpClient(client, HttpPolicy(max_bytes=1000))
        with pytest.raises(ConnectorError, match="payload_too_large"):
            await NewsApiConnector(http, api_key="test").search(DiscoveryRequest("hello"))


@pytest.mark.anyio
async def test_non_retryable_auth_error() -> None:
    count = 0

    def fake(_: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(403, json={"secret": "hidden"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        with pytest.raises(ConnectorError, match="http_403") as exc:
            await NewsApiConnector(ProviderHttpClient(client), api_key="auth-secret").search(
                DiscoveryRequest("hello")
            )
    assert count == 1
    assert "auth-secret" not in str(exc.value)
    assert "hidden" not in str(exc.value)


@pytest.mark.anyio
async def test_non_allowlisted_endpoint_is_rejected() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as c:
        with pytest.raises(ValueError, match="allowlisted"):
            await ProviderHttpClient(c).get_json(
                provider="newsapi",
                endpoint="http://169.254.169.254/metadata",
                parameters={},
                headers={},
            )


@pytest.mark.anyio
async def test_provider_error_payload_is_sanitized() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "error", "message": "key-secret"})
        )
    ) as c:
        with pytest.raises(ConnectorError, match="provider_returned_error") as exc:
            await NewsApiConnector(ProviderHttpClient(c), api_key="key-secret").search(
                DiscoveryRequest("test")
            )
    assert "key-secret" not in str(exc.value)


def test_offline_configuration_and_validation() -> None:
    cfg = ConnectorConfiguration()
    assert cfg.enabled_providers() == ()
    # No client instantiated: an empty configuration has no enabled providers.
    with pytest.raises(ValueError):
        DiscoveryRequest("   ")
    with pytest.raises(ValueError):
        DiscoveryRequest("hi", limit=0)
    with pytest.raises(ValueError):
        DiscoveryRequest("hi", language="english")
    assert timestamp("bad") is None
    assert article_identity("http://127.0.0.1/private") is None


@pytest.mark.anyio
async def test_empty_fact_check_response() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    ) as client:
        result = await GoogleFactCheckConnector(ProviderHttpClient(client), api_key="a").search(
            DiscoveryRequest("new claim")
        )
    assert result.hits == ()


@pytest.mark.anyio
async def test_no_keys_means_no_connectors() -> None:
    from apps.api.connectors.registry import build_connectors

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as c:
        http = ProviderHttpClient(c)
        assert build_connectors(http, ConnectorConfiguration()) == ()
        configs = ConnectorConfiguration(newsapi_key="news", google_factcheck_key="google")
        assert configs.enabled_providers() == ("newsapi", "google_factcheck")
        assert len(build_connectors(http, configs)) == 2


@pytest.mark.anyio
async def test_transport_failure_is_sanitized_and_bounded() -> None:
    count = 0

    def fake(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        raise httpx.ConnectError("sensitive transport message", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        http = ProviderHttpClient(client, policy=HttpPolicy(max_attempts=2, backoff_seconds=0))
        with pytest.raises(ConnectorError, match="network_error") as exc:
            await NewsApiConnector(http, api_key="not-printed").search(DiscoveryRequest("hi"))
    assert count == 2
    assert "not-printed" not in str(exc.value)
    assert "sensitive" not in str(exc.value)
