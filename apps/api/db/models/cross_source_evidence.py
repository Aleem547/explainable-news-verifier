"""Auditable passage-level NLI inputs and their cross-source contribution roles."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class CrossSourceEvidence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "cross_source_evidence"
    __table_args__ = (
        UniqueConstraint("assessment_id", "passage_id", name="uq_cross_source_passage"),
        CheckConstraint("nli_confidence BETWEEN 0 AND 1", name="confidence_bounds"),
        CheckConstraint(
            "stance IN ('ENTAILMENT', 'CONTRADICTION', 'NEUTRAL')", name="valid_stance"
        ),
    )

    assessment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cross_source_assessments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    passage_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_passages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    context_assessment_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_context_assessments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    model_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model_runs.id", ondelete="RESTRICT"), nullable=True
    )
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    stance: Mapped[str] = mapped_column(String(16), nullable=False)
    nli_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    nli_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    admissible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
