"""Append-only analysis of source families for a specified claim and snapshot set."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class CrossSourceAssessment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "cross_source_assessments"
    __table_args__ = (
        CheckConstraint("length(claim_sha256) = 64", name="claim_hash_length"),
        CheckConstraint("confidence_threshold > 0 AND confidence_threshold <= 1", name="threshold_bounds"),
        CheckConstraint("input_count BETWEEN 1 AND 100", name="input_count_bounds"),
        CheckConstraint("decisive_count BETWEEN 0 AND input_count", name="decisive_count_bounds"),
    )

    independence_assessment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("independence_assessments.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    claim_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    input_count: Mapped[int] = mapped_column(Integer, nullable=False)
    decisive_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(48), nullable=False)
    independence_status: Mapped[str] = mapped_column(String(40), nullable=False)
    supporting_families: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    refuting_families: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    mixed_families: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
