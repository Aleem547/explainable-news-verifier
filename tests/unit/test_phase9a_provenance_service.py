"""Service contract tests without writing to a real development database."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from apps.api.services.provenance import (
    attach_evidence_provenance,
    capture_document_version,
    record_retrieval_observation,
)
from ml.provenance.identity import sha256_text


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_capture_document_snapshot_updates_current_cache() -> None:
    document_id = uuid4()
    document = SimpleNamespace(
        url="HTTPS://Example.org/Story#fragment",
        published_at=None,
        content_hash=None,
        raw_text=None,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[document, None]),
        add=Mock(),
        flush=AsyncMock(),
    )
    version = await capture_document_version(
        session,
        document_id=document_id,
        text="A documented statement.",
        retrieved_at=datetime.now(UTC),
    )
    assert version.version_number == 1
    assert version.original_url == "https://example.org/Story"
    assert document.content_hash == sha256_text("A documented statement.")
    assert document.raw_text == "A documented statement."
    session.add.assert_called_once_with(version)
    session.flush.assert_awaited_once()


@pytest.mark.anyio
async def test_capture_identical_latest_snapshot_is_idempotent() -> None:
    document_id = uuid4()
    text = "Same bytes"
    last_version = SimpleNamespace(
        content_sha256=sha256_text(text),
        content_text=text,
        version_number=2,
    )
    document = SimpleNamespace(url="https://example.org/a", published_at=None)
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[document, last_version]),
        add=Mock(),
        flush=AsyncMock(),
    )
    result = await capture_document_version(
        session, document_id=document_id, text=text, retrieved_at=datetime.now(UTC)
    )
    assert result is last_version
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.anyio
async def test_snapshot_rejects_naive_datetime() -> None:
    session = SimpleNamespace(scalar=AsyncMock())
    with pytest.raises(ValueError, match="timezone-aware"):
        await capture_document_version(
            session, document_id=uuid4(), text="valid", retrieved_at=datetime(2026, 1, 1)
        )
    session.scalar.assert_not_awaited()


@pytest.mark.anyio
async def test_retrieval_observation_rejects_wrong_document_source() -> None:
    source_id = uuid4()
    document_id = uuid4()
    session = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(source_id=uuid4())))
    with pytest.raises(ValueError, match="source does not own"):
        await record_retrieval_observation(
            session,
            source_id=source_id,
            provider="ProviderA",
            requested_url="https://example.org/item",
            outcome="HTTP_ERROR",
            observed_at=datetime.now(UTC),
            document_id=document_id,
        )


@pytest.mark.anyio
async def test_evidence_provenance_rejects_wrong_snapshot() -> None:
    evidence_id, version_id = uuid4(), uuid4()
    evidence = SimpleNamespace(document_id=uuid4())
    version = SimpleNamespace(document_id=uuid4())
    session = SimpleNamespace(get=AsyncMock(side_effect=[evidence, version]))
    with pytest.raises(ValueError, match="different documents"):
        await attach_evidence_provenance(
            session,
            evidence_id=evidence_id,
            document_version_id=version_id,
            extraction_method="sentence",
        )
