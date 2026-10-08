import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from apps.api.connectors.contracts import (
    ContentKind,
    DiscoveryResult,
    ExternalDiscoveryHit,
    Provider,
)
from apps.api.services.external_ingestion import (
    ingest_discovery_result,
    ingest_supplied_content,
)
from ml.ingestion.passages import split_passages


def example_hit() -> ExternalDiscoveryHit:
    return ExternalDiscoveryHit(
        provider=Provider.NEWSAPI,
        kind=ContentKind.NEWS_ARTICLE,
        url="https://example.org/article",
        publisher_domain="example.org",
        publisher_name="Example Press",
        title="A published example",
        snippet="Preview only",
        discovered_at=datetime.now(UTC),
        published_at=None,
    )


def test_discovery_writes_only_metadata() -> None:
    source = SimpleNamespace(id=uuid4())
    document = SimpleNamespace(id=uuid4(), source_id=source.id)
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=document)
    result = DiscoveryResult(provider=Provider.NEWSAPI, query="a claim", hits=(example_hit(),))
    with patch(
        "apps.api.services.external_ingestion.register_source", new_callable=AsyncMock
    ) as register:
        register.return_value = source
        outcome = asyncio.run(ingest_discovery_result(session, result))
    assert outcome.documents_seen == 1
    assert outcome.discovery_records_seen == 1
    assert session.execute.await_count == 2
    assert session.add.call_count == 0


def test_provider_mismatch_refused_without_writes() -> None:
    result = DiscoveryResult(
        provider=Provider.GOOGLE_FACTCHECK, query="claim", hits=(example_hit(),)
    )
    session = MagicMock()
    with pytest.raises(ValueError, match="provider"):
        asyncio.run(ingest_discovery_result(session, result))
    session.execute.assert_not_called()


def test_no_storage_without_permission() -> None:
    session = MagicMock()
    with pytest.raises(ValueError, match="authorization"):
        asyncio.run(
            ingest_supplied_content(
                session,
                url="https://example.org/article",
                text="full source content",
                retrieved_at=datetime.now(UTC),
            )
        )
    session.scalar.assert_not_called()


def test_supplied_content_prepares_passages_and_outbox() -> None:
    document = SimpleNamespace(id=uuid4(), source_id=uuid4())
    snapshot = SimpleNamespace(id=uuid4(), document_id=document.id)
    observation = SimpleNamespace(id=uuid4())
    text = "Licensed sentence. " * 100
    session = MagicMock()
    session.scalar = AsyncMock(return_value=document)
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    with (
        patch(
            "apps.api.services.external_ingestion.capture_document_version",
            new_callable=AsyncMock,
        ) as cap,
        patch(
            "apps.api.services.external_ingestion.record_retrieval_observation",
            new_callable=AsyncMock,
        ) as obs,
    ):
        cap.return_value = snapshot
        obs.return_value = observation
        result = asyncio.run(
            ingest_supplied_content(
                session,
                url="https://example.org/article",
                text=text,
                retrieved_at=datetime.now(UTC),
                storage_authorized=True,
            )
        )
        assert cap.await_count == 1
        assert obs.await_count == 1
        assert obs.await_args.kwargs["outcome"] == "FETCHED"
    assert result.document_version_id == snapshot.id
    assert result.retrieval_observation_id == observation.id
    assert result.passages_count == len(split_passages(text))
    assert session.add.call_count == result.passages_count
    assert session.execute.await_count == 1


def test_same_snapshot_reuses_passages() -> None:
    text = "Document with simple content. " * 60
    spans = split_passages(text)
    existing = [
        SimpleNamespace(
            ordinal=s.ordinal,
            start_offset=s.start_offset,
            end_offset=s.end_offset,
            passage_sha256=s.sha256,
        )
        for s in spans
    ]
    doc = SimpleNamespace(id=uuid4(), source_id=uuid4())
    snapshot = SimpleNamespace(id=uuid4())
    session = MagicMock()
    session.scalar = AsyncMock(return_value=doc)
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: existing))
    session.execute = AsyncMock()
    with (
        patch(
            "apps.api.services.external_ingestion.capture_document_version",
            new_callable=AsyncMock,
        ) as cap,
        patch(
            "apps.api.services.external_ingestion.record_retrieval_observation",
            new_callable=AsyncMock,
        ) as obs,
    ):
        cap.return_value = snapshot
        obs.return_value = SimpleNamespace(id=uuid4())
        result = asyncio.run(
            ingest_supplied_content(
                session,
                url="https://example.org/article",
                text=text,
                retrieved_at=datetime.now(UTC),
                storage_authorized=True,
            )
        )
    assert result.passages_count == len(spans)
    session.add.assert_not_called()
    session.execute.assert_awaited_once()


def test_mismatched_passages_refused() -> None:
    doc = SimpleNamespace(id=uuid4(), source_id=uuid4())
    session = MagicMock()
    session.scalar = AsyncMock(return_value=doc)
    session.scalars = AsyncMock(
        return_value=SimpleNamespace(
            all=lambda: [
                SimpleNamespace(ordinal=0, start_offset=4, end_offset=99, passage_sha256="bad")
            ]
        )
    )
    with patch(
        "apps.api.services.external_ingestion.capture_document_version", new_callable=AsyncMock
    ) as cap:
        cap.return_value = SimpleNamespace(id=uuid4())
        with pytest.raises(ValueError, match="disagrees"):
            asyncio.run(
                ingest_supplied_content(
                    session,
                    url="https://example.org/article",
                    text="Real content " * 70,
                    retrieved_at=datetime.now(UTC),
                    storage_authorized=True,
                )
            )


def test_naive_timestamp_refused() -> None:
    with pytest.raises(ValueError, match="timezone"):
        asyncio.run(
            ingest_supplied_content(
                MagicMock(),
                url="https://example.org/article",
                text="Sample",
                retrieved_at=datetime(2026, 1, 1),
                storage_authorized=True,
            )
        )
