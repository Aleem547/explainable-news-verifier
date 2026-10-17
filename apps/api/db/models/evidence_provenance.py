"""The particular document snapshot on which an evidence passage is grounded."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class EvidenceProvenance(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evidence_provenance"
    __table_args__ = (
        UniqueConstraint("evidence_id", name="uq_evidence_provenance_evidence_id"),
    )

    evidence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    observation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("retrieval_observations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(100), nullable=False)
    locator_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
