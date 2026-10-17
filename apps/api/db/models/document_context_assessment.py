"""Append-only, claim-scoped metadata assessment for exact document snapshots."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class DocumentContextAssessment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_context_assessments"
    __table_args__ = (
        CheckConstraint(
            "temporal_relation IN ('BEFORE_REFERENCE', 'SAME_REFERENCE_DAY', "
            "'AFTER_REFERENCE', 'UNKNOWN')", name="valid_temporal_relation"
        ),
        CheckConstraint(
            "freshness_status IN ('NOT_REQUESTED', 'UNKNOWN', 'WITHIN_WINDOW', "
            "'OLDER_THAN_WINDOW', 'FUTURE_DATED')", name="valid_freshness_status"
        ),
        CheckConstraint(
            "max_age_days IS NULL OR max_age_days BETWEEN 1 AND 36500",
            name="valid_max_age_days",
        ),
    )

    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    source_profile_observation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_profile_observations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    retrieval_observation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("retrieval_observations.id", ondelete="SET NULL"),
        nullable=True,
    )
    claim_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    max_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temporal_relation: Mapped[str] = mapped_column(String(32), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
