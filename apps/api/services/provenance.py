"""Auditable, transaction-bound Phase 9A snapshot and provenance operations.

No network, source-ranking, or claim-verdict decisions are performed here.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.document import Document
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.evidence import Evidence
from apps.api.db.models.evidence_provenance import EvidenceProvenance
from apps.api.db.models.retrieval_observation import RetrievalObservation
from ml.provenance.identity import canonical_public_url, sha256_text

RetrievalOutcome = Literal["FETCHED", "NOT_MODIFIED", "HTTP_ERROR", "NETWORK_ERROR"]


def _require_aware_time(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware.")


async def capture_document_version(
    session: AsyncSession,
    *,
    document_id: UUID,
    text: str,
    retrieved_at: datetime,
    content_type: str | None = None,
) -> DocumentVersion:
    """Create a snapshot iff the content differs from the latest snapshot.

    A row lock on the parent document serializes concurrent version assignments.
    Content reverting to an earlier hash creates a *new* version, preserving history.
    Caller controls the transaction and must commit or roll it back.
    """
    _require_aware_time(retrieved_at)
    if not text.strip():
        raise ValueError("Document snapshot text cannot be blank.")
    if content_type is not None and len(content_type) > 128:
        raise ValueError("Content type exceeds 128 characters.")

    document = await session.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        raise ValueError("Document does not exist.")

    latest = await session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )
    fingerprint = sha256_text(text)
    if latest is not None and latest.content_sha256 == fingerprint and latest.content_text == text:
        return latest

    snapshot = DocumentVersion(
        document_id=document_id,
        version_number=1 if latest is None else latest.version_number + 1,
        content_sha256=fingerprint,
        content_text=text,
        original_url=canonical_public_url(document.url),
        retrieved_at=retrieved_at,
        published_at_snapshot=document.published_at,
        content_type=content_type,
    )
    session.add(snapshot)
    document.content_hash = fingerprint
    document.raw_text = text
    await session.flush()
    return snapshot


async def record_retrieval_observation(
    session: AsyncSession,
    *,
    source_id: UUID,
    provider: str,
    requested_url: str,
    outcome: RetrievalOutcome,
    observed_at: datetime,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
    final_url: str | None = None,
    http_status: int | None = None,
    error_code: str | None = None,
    etag: str | None = None,
    last_modified_header: str | None = None,
) -> RetrievalObservation:
    """Log a retrieval attempt, including 304s and failures without document bodies."""
    _require_aware_time(observed_at)
    if not provider.strip() or len(provider) > 100:
        raise ValueError("Provider must have between 1 and 100 characters.")
    if http_status is not None and not 100 <= http_status <= 599:
        raise ValueError("Invalid HTTP status.")
    if error_code is not None and len(error_code) > 100:
        raise ValueError("Error code is too long.")
    if etag is not None and len(etag) > 512:
        raise ValueError("ETag is too long.")
    if last_modified_header is not None and len(last_modified_header) > 255:
        raise ValueError("Last-Modified header is too long.")
    if outcome == "FETCHED" and (document_id is None or document_version_id is None):
        raise ValueError("FETCHED observations require a document and its version.")
    if document_version_id is not None and document_id is None:
        raise ValueError("A version must identify its parent document.")

    if document_id is not None:
        document = await session.get(Document, document_id)
        if document is None or document.source_id != source_id:
            raise ValueError("Observation source does not own the document.")
    if document_version_id is not None:
        version = await session.get(DocumentVersion, document_version_id)
        if version is None or version.document_id != document_id:
            raise ValueError("Observation version does not match the document.")

    observation = RetrievalObservation(
        source_id=source_id,
        provider=provider.strip(),
        requested_url=canonical_public_url(requested_url),
        final_url=canonical_public_url(final_url) if final_url else None,
        outcome=outcome,
        observed_at=observed_at,
        document_id=document_id,
        document_version_id=document_version_id,
        http_status=http_status,
        error_code=error_code,
        etag=etag,
        last_modified_header=last_modified_header,
    )
    session.add(observation)
    await session.flush()
    return observation


async def attach_evidence_provenance(
    session: AsyncSession,
    *,
    evidence_id: UUID,
    document_version_id: UUID,
    extraction_method: str,
    observation_id: UUID | None = None,
    locator_json: dict[str, object] | None = None,
) -> EvidenceProvenance:
    """Attach an evidence passage to its actual document snapshot once.

    A mismatched snapshot is rejected even if both IDs exist. This deliberately
    does not assert that the publisher is independent or trustworthy.
    """
    if not extraction_method.strip() or len(extraction_method) > 100:
        raise ValueError("Extraction method must have between 1 and 100 characters.")

    evidence = await session.get(Evidence, evidence_id)
    version = await session.get(DocumentVersion, document_version_id)
    if evidence is None or version is None:
        raise ValueError("Evidence or document snapshot does not exist.")
    if evidence.document_id != version.document_id:
        raise ValueError("Evidence and snapshot belong to different documents.")

    if observation_id is not None:
        observation = await session.get(RetrievalObservation, observation_id)
        if observation is None or observation.document_version_id != document_version_id:
            raise ValueError("Retrieval observation does not match the snapshot.")

    existing = await session.scalar(
        select(EvidenceProvenance).where(EvidenceProvenance.evidence_id == evidence_id)
    )
    if existing is not None:
        if existing.document_version_id != document_version_id:
            raise ValueError("Evidence already has provenance for another snapshot.")
        return existing

    provenance = EvidenceProvenance(
        evidence_id=evidence_id,
        document_version_id=document_version_id,
        observation_id=observation_id,
        original_url=version.original_url,
        extraction_method=extraction_method.strip(),
        locator_json=locator_json,
    )
    session.add(provenance)
    await session.flush()
    return provenance
