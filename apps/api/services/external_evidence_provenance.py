"""Phase 13D.3: read-only auditing of external passage provenance.

Revalidates the stored chain from Phase 13D.1 candidates to an exact document
snapshot, source registry entry and a successful Phase 13C fetch observation.
A successful audit means *traceable*, NOT credible, factually correct, or
independent evidence. It never writes to PostgreSQL or contacts a URL.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Sequence
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.enums import DocumentType
from apps.api.db.models.document import Document
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.db.models.source import Source
from apps.api.services.external_passage_retrieval import ExternalPassageCandidate
from ml.provenance.identity import canonical_public_url, normalize_source_domain


class ExternalProvenanceError(ValueError):
    """Stored evidence chain is incomplete or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class AuditedExternalPassage:
    candidate: ExternalPassageCandidate
    fetch_observation_id: UUID
    fetch_observed_at: datetime
    snapshot_version_number: int
    snapshot_sha256: str
    passage_start_offset: int
    passage_end_offset: int
    reported_publication_at: datetime | None
    traceable: bool = True
    nli_evaluated: bool = False
    independently_verified: bool = False
    independent_corroboration_established: bool = False


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _validate_candidate(candidate: ExternalPassageCandidate) -> None:
    if not isinstance(candidate, ExternalPassageCandidate):
        raise ExternalProvenanceError("invalid_candidate")
    if candidate.independently_verified or candidate.nli_evaluated or candidate.independent_corroboration_established:
        raise ExternalProvenanceError("candidate_already_assessed")
    if not all(isinstance(x, UUID) for x in (candidate.passage_id, candidate.document_version_id, candidate.document_id, candidate.source_id)):
        raise ExternalProvenanceError("invalid_candidate_ids")
    if not isinstance(candidate.rank, int) or isinstance(candidate.rank, bool) or candidate.rank < 1:
        raise ExternalProvenanceError("invalid_candidate_rank")
    score = candidate.lexical_relevance_score
    if not isinstance(score, (float, int)) or isinstance(score, bool) or not math.isfinite(score) or score <= 0:
        raise ExternalProvenanceError("invalid_candidate_score")
    if not isinstance(candidate.passage_text, str) or not candidate.passage_text:
        raise ExternalProvenanceError("invalid_candidate_passage")
    if _digest(candidate.passage_text) != candidate.passage_sha256:
        raise ExternalProvenanceError("invalid_candidate_passage_hash")
    if not _aware(candidate.retrieved_at):
        raise ExternalProvenanceError("invalid_candidate_retrieved_at")
    if not isinstance(candidate.publisher_name, str) or not candidate.publisher_name.strip():
        raise ExternalProvenanceError("invalid_candidate_source")
    try:
        domain = normalize_source_domain(candidate.publisher_domain)
        url = canonical_public_url(candidate.original_url)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise ValueError("HTTPS required")
        hostname = parsed.hostname
        if not hostname or not (hostname == domain or hostname.endswith("." + domain)):
            raise ValueError("Publisher/URL mismatch")
        if url != candidate.original_url:
            raise ValueError("Non-canonical document URL")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ExternalProvenanceError("invalid_candidate_url_or_publisher") from exc


def build_external_provenance_statement(passage_ids: Sequence[UUID]):
    """Parameterized SELECT. Use only bounded, distinct passage UUIDs."""
    if not 1 <= len(passage_ids) <= 20 or len(set(passage_ids)) != len(passage_ids) or not all(isinstance(x, UUID) for x in passage_ids):
        raise ExternalProvenanceError("invalid_passage_id_batch")

    # The correlated subquery selects one legitimate observation for exactly
    # this version and source. It cannot accept discovery-only metadata.
    last_fetch = (
        select(RetrievalObservation.id)
        .where(
            RetrievalObservation.document_id == Document.id,
            RetrievalObservation.document_version_id == DocumentVersion.id,
            RetrievalObservation.source_id == Source.id,
            RetrievalObservation.provider == "secure_article_fetch_v1",
            RetrievalObservation.outcome == "FETCHED",
            RetrievalObservation.final_url == DocumentVersion.original_url,
            RetrievalObservation.metadata_json["independently_verified"].as_boolean().is_(False),
        )
        .order_by(RetrievalObservation.observed_at.desc(), RetrievalObservation.id.desc())
        .limit(1)
        .correlate(Document, DocumentVersion, Source)
        .scalar_subquery()
    )
    latest = (
        select(DocumentVersion.id)
        .where(DocumentVersion.document_id == Document.id)
        .order_by(DocumentVersion.version_number.desc(), DocumentVersion.id.desc())
        .limit(1)
        .correlate(Document)
        .scalar_subquery()
    )
    return (
        select(
            DocumentPassage.id.label("passage_id"),
            DocumentPassage.document_version_id,
            DocumentPassage.text.label("passage_text"),
            DocumentPassage.passage_sha256,
            DocumentPassage.start_offset,
            DocumentPassage.end_offset,
            DocumentVersion.id.label("version_id"),
            DocumentVersion.document_id,
            DocumentVersion.version_number,
            DocumentVersion.original_url,
            DocumentVersion.content_text,
            DocumentVersion.content_sha256,
            DocumentVersion.retrieved_at,
            DocumentVersion.published_at_snapshot,
            Document.id.label("parent_document_id"),
            Document.url.label("document_url"),
            Document.source_id.label("document_source_id"),
            Source.id.label("source_id"),
            Source.name.label("publisher_name"),
            Source.domain.label("publisher_domain"),
            RetrievalObservation.id.label("observation_id"),
            RetrievalObservation.document_id.label("observation_document_id"),
            RetrievalObservation.document_version_id.label("observation_version_id"),
            RetrievalObservation.source_id.label("observation_source_id"),
            RetrievalObservation.final_url.label("fetch_final_url"),
            RetrievalObservation.provider.label("fetch_provider"),
            RetrievalObservation.outcome.label("fetch_outcome"),
            RetrievalObservation.metadata_json.label("fetch_metadata"),
            RetrievalObservation.observed_at.label("fetch_observed_at"),
        )
        .select_from(DocumentPassage)
        .join(DocumentVersion, DocumentVersion.id == DocumentPassage.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(Source, Source.id == Document.source_id)
        .join(RetrievalObservation, RetrievalObservation.id == last_fetch)
        .where(
            DocumentPassage.id.in_(passage_ids),
            Document.document_type == DocumentType.ARTICLE,
            Source.is_active.is_(True),
            DocumentVersion.id == latest,
            DocumentVersion.original_url == Document.url,
        )
    )


def _validate_stored_record(candidate: ExternalPassageCandidate, record: object) -> AuditedExternalPassage:
    """Fail closed for mixed identity, altered snapshots, or missing fetch trail."""
    if not all((
        record.passage_id == candidate.passage_id,
        record.document_version_id == candidate.document_version_id == record.version_id,
        record.document_id == candidate.document_id == record.parent_document_id,
        record.source_id == candidate.source_id == record.document_source_id,
        record.observation_document_id == candidate.document_id,
        record.observation_version_id == candidate.document_version_id,
        record.observation_source_id == candidate.source_id,
        record.publisher_name == candidate.publisher_name,
        record.publisher_domain == candidate.publisher_domain,
        record.original_url == candidate.original_url == record.document_url == record.fetch_final_url,
        record.retrieved_at == candidate.retrieved_at,
        record.passage_text == candidate.passage_text,
        record.passage_sha256 == candidate.passage_sha256,
    )):
        raise ExternalProvenanceError("source_attribution_mismatch")
    if (
        not isinstance(record.content_text, str)
        or _digest(record.content_text) != record.content_sha256
        or not isinstance(record.passage_text, str)
        or _digest(record.passage_text) != record.passage_sha256
        or not isinstance(record.start_offset, int)
        or not isinstance(record.end_offset, int)
        or not (0 <= record.start_offset < record.end_offset <= len(record.content_text))
        or record.content_text[record.start_offset:record.end_offset] != record.passage_text
    ):
        raise ExternalProvenanceError("stored_snapshot_or_passage_corrupted")
    if (
        not isinstance(record.version_number, int)
        or record.version_number < 1
        or not isinstance(record.observation_id, UUID)
        or record.fetch_provider != "secure_article_fetch_v1"
        or record.fetch_outcome != "FETCHED"
        or not isinstance(record.fetch_metadata, dict)
        or record.fetch_metadata.get("independently_verified") is not False
        or not _aware(record.retrieved_at)
        or not _aware(record.fetch_observed_at)
        or (record.published_at_snapshot is not None and not _aware(record.published_at_snapshot))
    ):
        raise ExternalProvenanceError("invalid_fetch_or_time_provenance")
    # A verified URL identity is NOT proof that this publisher is independent.
    _validate_candidate(candidate)
    return AuditedExternalPassage(
        candidate=candidate,
        fetch_observation_id=record.observation_id,
        fetch_observed_at=record.fetch_observed_at,
        snapshot_version_number=record.version_number,
        snapshot_sha256=record.content_sha256,
        passage_start_offset=record.start_offset,
        passage_end_offset=record.end_offset,
        reported_publication_at=record.published_at_snapshot,
    )


async def audit_external_passage_provenance(
    session: AsyncSession,
    candidates: Sequence[ExternalPassageCandidate],
) -> tuple[AuditedExternalPassage, ...]:
    """Audit up to 20 candidates without modifying state; return input order.

    No missing candidate is silently ignored. Caller can roll back or quarantine
    the complete result if any provenance record is missing or invalid.
    """
    if not isinstance(candidates, (list, tuple)) or len(candidates) > 20:
        raise ExternalProvenanceError("invalid_candidate_batch")
    if not candidates:
        return ()
    ids: set[UUID] = set()
    for candidate in candidates:
        _validate_candidate(candidate)
        if candidate.passage_id in ids:
            raise ExternalProvenanceError("duplicate_passage_id")
        ids.add(candidate.passage_id)
    stmt = build_external_provenance_statement([c.passage_id for c in candidates])
    rows = (await session.execute(stmt)).all()
    index: dict[UUID, object] = {}
    for record in rows:
        if record.passage_id in index:
            raise ExternalProvenanceError("nonunique_stored_provenance")
        index[record.passage_id] = record
    if ids != index.keys():
        raise ExternalProvenanceError("missing_or_unfetched_passage_provenance")
    return tuple(_validate_stored_record(candidate, index[candidate.passage_id]) for candidate in candidates)
