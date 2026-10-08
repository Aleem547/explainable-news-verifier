"""No API keys, no live requests; failures cannot make snippets into evidence."""

import asyncio
from types import SimpleNamespace

import pytest

from apps.api.connectors.contracts import DiscoveryResult, Provider
from apps.api.connectors.http_client import ConnectorError
from apps.api.connectors.registry import ConnectorConfiguration
from apps.api.schemas.multisource import ExternalDiscoveryRequest
from apps.api.services import multisource_discovery


class FakeConnector:
    def __init__(self, name: str, fail: bool = False):
        self.name = name
        self.fail = fail
        self.calls = 0

    async def search(self, request: object) -> DiscoveryResult:
        self.calls += 1
        if self.fail:
            raise ConnectorError(self.name, "network_error")
        return DiscoveryResult(provider=Provider.NEWSAPI, query="sample", hits=())


async def fake_ingest(session: object, result: DiscoveryResult) -> SimpleNamespace:
    return SimpleNamespace(documents_seen=0)


def invoke(monkeypatch: pytest.MonkeyPatch, connectors: list[FakeConnector]):
    monkeypatch.setattr(multisource_discovery, "build_connectors", lambda http, cfg: connectors)
    monkeypatch.setattr(multisource_discovery, "ingest_discovery_result", fake_ingest)
    return asyncio.run(
        multisource_discovery.discover_external_metadata(
            object(),  # type: ignore[arg-type]
            ExternalDiscoveryRequest(query="sample"),
            object(),  # type: ignore[arg-type]
            ConnectorConfiguration(),
        )
    )


def test_no_configured_provider_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(multisource_discovery.NoConfiguredProviderError):
        invoke(monkeypatch, [])


def test_provider_failure_cannot_be_reported_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(multisource_discovery.NoConfiguredProviderError):
        invoke(monkeypatch, [FakeConnector("newsapi", fail=True)])


def test_successful_discovery_is_only_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    result = invoke(monkeypatch, [FakeConnector("newsapi")])
    assert result.discovered_hits == 0
    assert "No full article" in result.warning
    assert result.failed_providers == []
