from __future__ import annotations

from uuid import UUID

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from apps.api.db.enums import VerificationVerdict


class VerificationResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "verification_results"

    atomic_claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("atomic_claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    analysis_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analysis_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    fusion_model_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    verdict: Mapped[VerificationVerdict] = mapped_column(
        SQLEnum(VerificationVerdict, name="verification_verdict"),
        nullable=False,
        index=True,
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    uncertainty: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    corroboration_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    support_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    refute_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    neutral_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    decision_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    atomic_claim = relationship(
        "AtomicClaim",
        back_populates="verification_results",
    )
