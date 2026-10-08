"""Phase 9D audited, transaction-bound source and time-context operations.

The caller owns the transaction. These records are *metadata assessments*;
no claim-level credibility or veracity is inferred or stored here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.document import Document
from apps.api.db.models.document_context_assessment import DocumentContextAssessment
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.db.models.source import Source
from apps.api.db.models.source_profile_observation import SourceProfileObservation
from ml.provenance.identity import canonical_public_url, sha256_text
from ml.verification.source_context import (
    SourceObservationMethod,
    SourceProfileSignals,
    assess_context,
    require_aware,
)


def _safe_url(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValueError("Empty URL is not valid metadata; use None for unknown")
    return canonical_public_url(value)


async def record_source_profile(
    session: AsyncSession,
    *,
    source_id: UUID,
    observed_at: datetime,
    method: SourceObservationMethod,
    observed_url: str | None = None,
    publisher_name_reported: str | None = None,
    homepage_url: str | None = None,
    editorial_policy_url: str | None = None,
    corrections_policy_url: str | None = None,
    ownership_disclosure_url: str | None = None,
    notes: str | None = None,
) -> SourceProfileObservation:
    """Record supplied publisher metadata, *without verifying its truth*.

    Metadata is recorded as reported by a publisher/provider or manual reviewer.
    This function never fetches URLs and never updates older observations.
    """
    require_aware(observed_at)
    if not isinstance(method, SourceObservationMethod):
        raise ValueError("Use a declared SourceObservationMethod")
    if method == SourceObservationMethod.PUBLISHER_PAGE and not observed_url:
        raise ValueError("Publisher-page observations require the observed page URL")
    if notes is not None and len(notes) > 4000:
        raise ValueError("Profile notes exceed 4000 characters")
    if publisher_name_reported is not None and not 1 <= len(publisher_name_reported.strip()) <= 255:
        raise ValueError("Reported publisher name must contain 1 to 255 characters")
    source = await session.get(Source, source_id)
    if source is None:
        raise ValueError("Source does not exist")
    profile = SourceProfileObservation(
        source_id=source_id,
        observed_at=observed_at,
        method=method.value,
        observed_url=_safe_url(observed_url),
        publisher_name_reported=publisher_name_reported.strip()
        if publisher_name_reported is not None
        else None,
        homepage_url=_safe_url(homepage_url),
        editorial_policy_url=_safe_url(editorial_policy_url),
        corrections_policy_url=_safe_url(corrections_policy_url),
        ownership_disclosure_url=_safe_url(ownership_disclosure_url),
        notes=notes,
    )
    session.add(profile)
    await session.flush()
    return profile


async def assess_document_context(
    session: AsyncSession,
    *,
    document_version_id: UUID,
    assessed_at: datetime,
    claim_text: str | None = None,
    reference_at: datetime | None = None,
    max_age_days: int | None = None,
    source_profile_observation_id: UUID | None = None,
    retrieval_observation_id: UUID | None = None,
) -> DocumentContextAssessment:
    """Audit metadata for one exact, unmodified document snapshot.

    An observed profile may be supplied or selected from source history; a
    successful retrieval observation may be supplied or selected from the
    snapshot. Neither creates a publisher trust score or changes a verdict.
    """
    require_aware(assessed_at)
    if reference_at is not None:
        require_aware(reference_at)
    if claim_text is not None and not claim_text.strip():
        raise ValueError("Use None or a nonempty claim")

    version = await session.get(DocumentVersion, document_version_id)
    if version is None:
        raise ValueError("Document version does not exist")
    document = await session.get(Document, version.document_id)
    if document is None:
        raise ValueError("Snapshot parent document does not exist")
    require_aware(version.retrieved_at)
    if version.retrieved_at > assessed_at:
        raise ValueError("Cannot assess a snapshot retrieved after the assessment time")
    if sha256_text(version.content_text) != version.content_sha256:
        raise ValueError("Stored document version does not match its SHA-256 digest")

    profile: SourceProfileObservation | None
    if source_profile_observation_id is not None:
        profile = await session.get(SourceProfileObservation, source_profile_observation_id)
        if profile is None or profile.source_id != document.source_id:
            raise ValueError("Profile does not belong to the document source")
        if profile.observed_at > assessed_at:
            raise ValueError("Profile contains future information")
    else:
        profile = await session.scalar(
            select(SourceProfileObservation)
            .where(
                SourceProfileObservation.source_id == document.source_id,
                SourceProfileObservation.observed_at <= assessed_at,
            )
            .order_by(SourceProfileObservation.observed_at.desc(), SourceProfileObservation.id)
            .limit(1)
        )

    observation: RetrievalObservation | None
    if retrieval_observation_id is not None:
        observation = await session.get(RetrievalObservation, retrieval_observation_id)
        if (
            observation is None
            or observation.document_version_id != version.id
            or observation.document_id != document.id
            or observation.source_id != document.source_id
            or observation.outcome != "FETCHED"
        ):
            raise ValueError("Retrieval observation must be a matching successful fetch")
        if observation.observed_at > assessed_at:
            raise ValueError("Retrieval observation contains future information")
    else:
        observation = await session.scalar(
            select(RetrievalObservation)
            .where(
                RetrievalObservation.document_version_id == version.id,
                RetrievalObservation.document_id == document.id,
                RetrievalObservation.source_id == document.source_id,
                RetrievalObservation.outcome == "FETCHED",
                RetrievalObservation.observed_at <= assessed_at,
            )
            .order_by(RetrievalObservation.observed_at.desc(), RetrievalObservation.id)
            .limit(1)
        )

    signals = (
        SourceProfileSignals(
            method=SourceObservationMethod(profile.method),
            observed_at=profile.observed_at,
            publisher_name_reported=profile.publisher_name_reported,
            homepage_url=profile.homepage_url,
            editorial_policy_url=profile.editorial_policy_url,
            corrections_policy_url=profile.corrections_policy_url,
            ownership_disclosure_url=profile.ownership_disclosure_url,
        )
        if profile is not None
        else None
    )
    result = assess_context(
        published_at=version.published_at_snapshot,
        retrieved_at=version.retrieved_at,
        assessed_at=assessed_at,
        reference_at=reference_at,
        max_age_days=max_age_days,
        content_sha256=version.content_sha256,
        retrieval_observed=observation is not None,
        profile=signals,
    )
    assessment = DocumentContextAssessment(
        document_version_id=version.id,
        source_profile_observation_id=profile.id if profile is not None else None,
        retrieval_observation_id=observation.id if observation is not None else None,
        claim_sha256=sha256_text(claim_text.strip()) if claim_text is not None else None,
        assessed_at=assessed_at,
        reference_at=reference_at,
        max_age_days=max_age_days,
        temporal_relation=result.temporal_relation.value,
        freshness_status=result.freshness_status.value,
        metadata_flags=list(result.metadata_flags),
        warnings=list(result.warnings),
    )
    session.add(assessment)
    await session.flush()
    return assessment
