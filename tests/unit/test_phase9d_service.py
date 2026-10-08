"""Transaction-bound service tests with mocked async sessions, no DB access."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from apps.api.db.models.document import Document
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.db.models.source import Source
from apps.api.db.models.source_profile_observation import SourceProfileObservation
from apps.api.services.source_context import assess_document_context, record_source_profile
from ml.provenance.identity import sha256_text
from ml.verification.source_context import SourceObservationMethod

NOW = datetime(2026, 5, 10, tzinfo=UTC)


def session_fake(rows: dict[type[object], object]) -> MagicMock:
    session = MagicMock()

    async def get(model: type[object], _: object) -> object:
        return rows.get(model)

    session.get = get
    session.flush = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    return session


def test_profile_records_canonical_urls_and_does_not_commit() -> None:
    source_id = uuid4()
    session = session_fake({Source: SimpleNamespace(id=source_id)})
    profile = asyncio.run(
        record_source_profile(
            session,
            source_id=source_id,
            observed_at=NOW,
            method=SourceObservationMethod.PUBLISHER_PAGE,
            observed_url="HTTPS://EXAMPLE.ORG/Editorial#section",
            corrections_policy_url="https://example.org/corrections",
            publisher_name_reported=" Example Publisher ",
        )
    )
    assert profile.observed_url == "https://example.org/Editorial"
    assert profile.publisher_name_reported == "Example Publisher"
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    session.commit.assert_not_called()


def test_publisher_profile_requires_observed_url() -> None:
    session = session_fake({})
    with pytest.raises(ValueError, match="observed page URL"):
        asyncio.run(
            record_source_profile(
                session,
                source_id=uuid4(),
                observed_at=NOW,
                method=SourceObservationMethod.PUBLISHER_PAGE,
            )
        )
    session.add.assert_not_called()


def test_profile_rejects_non_public_url_and_no_write() -> None:
    session = session_fake({Source: SimpleNamespace(id=uuid4())})
    with pytest.raises(ValueError, match="public"):
        asyncio.run(
            record_source_profile(
                session,
                source_id=uuid4(),
                observed_at=NOW,
                method=SourceObservationMethod.MANUAL_RECORD,
                homepage_url="http://localhost/private",
            )
        )
    session.add.assert_not_called()


def test_profile_rejects_unknown_source() -> None:
    session = session_fake({})
    with pytest.raises(ValueError, match="Source does not exist"):
        asyncio.run(
            record_source_profile(
                session,
                source_id=uuid4(),
                observed_at=NOW,
                method=SourceObservationMethod.MANUAL_RECORD,
            )
        )


def document_rows() -> tuple[dict[type[object], object], object, object]:
    document_id, source_id, version_id = uuid4(), uuid4(), uuid4()
    text = "A licensed content example"
    version = SimpleNamespace(
        id=version_id,
        document_id=document_id,
        content_text=text,
        content_sha256=sha256_text(text),
        retrieved_at=NOW - timedelta(hours=1),
        published_at_snapshot=NOW - timedelta(days=35),
    )
    document = SimpleNamespace(id=document_id, source_id=source_id)
    return {DocumentVersion: version, Document: document}, version, document


def test_context_persists_descriptive_fields_only() -> None:
    rows, version, document = document_rows()
    profile = SimpleNamespace(
        id=uuid4(),
        source_id=document.source_id,
        observed_at=NOW - timedelta(days=1),
        method=SourceObservationMethod.PROVIDER_METADATA.value,
        publisher_name_reported="Example",
        homepage_url=None,
        editorial_policy_url=None,
        corrections_policy_url=None,
        ownership_disclosure_url=None,
    )
    observed = SimpleNamespace(
        id=uuid4(),
        document_version_id=version.id,
        document_id=document.id,
        source_id=document.source_id,
        outcome="FETCHED",
        observed_at=NOW - timedelta(minutes=40),
    )
    rows[SourceProfileObservation] = profile
    rows[RetrievalObservation] = observed
    session = session_fake(rows)
    saved = asyncio.run(
        assess_document_context(
            session,
            document_version_id=version.id,
            assessed_at=NOW,
            reference_at=NOW - timedelta(days=2),
            max_age_days=30,
            claim_text="Some claim text",
            source_profile_observation_id=profile.id,
            retrieval_observation_id=observed.id,
        )
    )
    assert saved.temporal_relation == "BEFORE_REFERENCE"
    assert saved.freshness_status == "OLDER_THAN_WINDOW"
    assert saved.claim_sha256 == sha256_text("Some claim text")
    assert "SOURCE_PROFILE_OBSERVED" in saved.metadata_flags
    assert "MATCHED_FETCH_OBSERVATION" in saved.metadata_flags
    session.flush.assert_awaited_once()
    session.commit.assert_not_called()


def test_context_rejects_tampered_snapshot() -> None:
    rows, version, _ = document_rows()
    version.content_text = "different content"
    session = session_fake(rows)
    with pytest.raises(ValueError, match="SHA-256"):
        asyncio.run(
            assess_document_context(session, document_version_id=version.id, assessed_at=NOW)
        )
    session.add.assert_not_called()


def test_context_rejects_snapshot_from_future() -> None:
    rows, version, _ = document_rows()
    version.retrieved_at = NOW + timedelta(days=1)
    session = session_fake(rows)
    with pytest.raises(ValueError, match="after the assessment"):
        asyncio.run(
            assess_document_context(session, document_version_id=version.id, assessed_at=NOW)
        )
    session.add.assert_not_called()


def test_context_rejects_mismatched_profile() -> None:
    rows, version, _ = document_rows()
    rows[SourceProfileObservation] = SimpleNamespace(id=uuid4(), source_id=uuid4())
    session = session_fake(rows)
    with pytest.raises(ValueError, match="does not belong"):
        asyncio.run(
            assess_document_context(
                session,
                document_version_id=version.id,
                assessed_at=NOW,
                source_profile_observation_id=uuid4(),
            )
        )


def test_context_rejects_failed_retrieval() -> None:
    rows, version, document = document_rows()
    rows[RetrievalObservation] = SimpleNamespace(
        id=uuid4(),
        document_version_id=version.id,
        document_id=document.id,
        source_id=document.source_id,
        outcome="HTTP_ERROR",
        observed_at=NOW,
    )
    session = session_fake(rows)
    with pytest.raises(ValueError, match="successful fetch"):
        asyncio.run(
            assess_document_context(
                session,
                document_version_id=version.id,
                assessed_at=NOW,
                retrieval_observation_id=uuid4(),
            )
        )


def test_context_missing_optional_metadata_is_explicit() -> None:
    rows, version, _ = document_rows()
    session = session_fake(rows)
    saved = asyncio.run(
        assess_document_context(session, document_version_id=version.id, assessed_at=NOW)
    )
    assert "SOURCE_PROFILE_NOT_OBSERVED" in saved.warnings
    assert "FETCH_OBSERVATION_NOT_FOUND" in saved.warnings
    assert saved.temporal_relation == "UNKNOWN"


def test_context_rejects_profile_not_yet_observed() -> None:
    rows, version, doc = document_rows()
    rows[SourceProfileObservation] = SimpleNamespace(
        id=uuid4(), source_id=doc.source_id, observed_at=NOW + timedelta(days=1)
    )
    session = session_fake(rows)
    with pytest.raises(ValueError, match="future"):
        asyncio.run(
            assess_document_context(
                session,
                document_version_id=version.id,
                assessed_at=NOW,
                source_profile_observation_id=uuid4(),
            )
        )
