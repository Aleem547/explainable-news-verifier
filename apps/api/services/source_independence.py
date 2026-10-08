"""Persist conservative evidence-family assessments for immutable snapshots.

The caller owns the transaction. No provider request, verification decision,
or automatic 'independent source' assertion is made.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.document import Document
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.independence_assessment import IndependenceAssessment
from apps.api.db.models.independence_pair import IndependencePair
from ml.verification.source_independence import Snapshot, assess_source_independence


@dataclass(frozen=True, slots=True)
class ReportedOrigin:
    origin_url: str
    observation_url: str


async def record_independence_assessment(
    session: AsyncSession,
    *,
    version_ids: Sequence[UUID],
    assessed_at: datetime,
    reported_origins: Mapping[UUID, ReportedOrigin] | None = None,
) -> IndependenceAssessment:
    """Assess available immutable full-text versions, recording every compared pair.

    Reported origins are unverified source claims with explicit observation URLs;
    they must NOT be used to mark the other articles independently corroborated.
    """
    if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise ValueError("assessed_at must be timezone-aware")
    if not 2 <= len(version_ids) <= 50 or len(set(version_ids)) != len(version_ids):
        raise ValueError("Require 2–50 distinct document version IDs")
    origins = reported_origins or {}
    if set(origins) - set(version_ids):
        raise ValueError("Origin observation refers to an unrequested version")

    rows = (
        await session.execute(
            select(DocumentVersion, Document.source_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.id.in_(version_ids))
        )
    ).all()
    if len(rows) != len(version_ids):
        raise ValueError("One or more document versions do not exist")
    snapshots = [
        Snapshot(
            version_id=version.id,
            source_id=source_id,
            text=version.content_text,
            reported_origin_url=origins[version.id].origin_url if version.id in origins else None,
            origin_observation_url=(
                origins[version.id].observation_url if version.id in origins else None
            ),
        )
        for version, source_id in rows
    ]
    summary = assess_source_independence(snapshots)
    assessment = IndependenceAssessment(
        assessed_at=assessed_at.astimezone(UTC),
        rule_version=summary.rule_version,
        snapshot_count=len(summary.version_ids),
        family_count=summary.family_count,
        version_ids=[str(key) for key in summary.version_ids],
        families=[[str(key) for key in group] for group in summary.families],
        warnings=list(summary.warnings),
    )
    session.add(assessment)
    await session.flush()
    for finding in summary.pairs:
        session.add(
            IndependencePair(
                assessment_id=assessment.id,
                left_version_id=finding.left_version_id,
                right_version_id=finding.right_version_id,
                relationship=finding.relationship.value,
                group_together=finding.group_together,
                basis=finding.basis,
                signals={"shared_5gram_jaccard": finding.shared_5gram_jaccard},
            )
        )
    await session.flush()
    return assessment
