"""Phase 13D.4 read-only, provenance-checked external source dependency audit.

The caller provides Phase 13D.1 candidates. Their Phase 13D.3 fetch and
snapshot provenance is re-verified before full-text source comparison.
This never commits or writes DB rows; no editorial independence is asserted.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.document import Document
from apps.api.db.models.document_version import DocumentVersion
from apps.api.services.external_evidence_provenance import audit_external_passage_provenance
from apps.api.services.external_passage_retrieval import ExternalPassageCandidate
from ml.verification.external_source_dependencies import (
    DependencyRiskReport, ReportedDependency, SourceDependencyError,
    assess_external_source_dependencies,
)
from ml.verification.source_independence import Snapshot


async def audit_external_source_dependencies(
    session: AsyncSession,
    candidates: Sequence[ExternalPassageCandidate],
    *,
    assessed_at: datetime,
    reported_links: Sequence[ReportedDependency] = (),
) -> DependencyRiskReport:
    """Audit full article snapshots, never discovery snippets/passage text alone.

    Call Phase 13D.3 first so that only latest, authorized fetch snapshots
    with auditable offsets/hashes enter this assessment.
    """
    if not isinstance(candidates, (tuple, list)) or not 2 <= len(candidates) <= 20:
        raise SourceDependencyError("candidate_batch_must_be_2_to_20")
    audits = await audit_external_passage_provenance(session, candidates)
    versions: dict[UUID, Snapshot] = {}
    for item in audits:
        if (not item.traceable or item.independently_verified or item.nli_evaluated
                or item.independent_corroboration_established):
            raise SourceDependencyError("candidate_is_not_unverified_traceable_content")
        candidate = item.candidate
        vid = candidate.document_version_id
        if vid in versions:
            existing = versions[vid]
            if existing.source_id != candidate.source_id:
                raise SourceDependencyError("conflicting_source_for_version")
            continue
        version = await session.get(DocumentVersion, vid)
        document = await session.get(Document, candidate.document_id)
        if (version is None or document is None
                or version.id != vid or version.document_id != document.id
                or document.source_id != candidate.source_id
                or version.original_url != candidate.original_url
                or document.url != candidate.original_url
                or version.retrieved_at != candidate.retrieved_at
                or version.version_number != item.snapshot_version_number
                or not isinstance(version.content_text, str)
                or sha256(version.content_text.encode("utf-8")).hexdigest() != item.snapshot_sha256
                or version.content_sha256 != item.snapshot_sha256):
            raise SourceDependencyError("snapshot_changed_since_provenance_audit")
        versions[vid] = Snapshot(
            version_id=vid, source_id=document.source_id, text=version.content_text,
        )
    if len(versions) < 2:
        raise SourceDependencyError("two_distinct_document_versions_required")
    return assess_external_source_dependencies(
        list(versions.values()), assessed_at=assessed_at,
        reported_links=tuple(reported_links),
    )
