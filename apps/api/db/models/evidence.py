from __future__ import annotations

from uuid import UUID

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from apps.api.db.enums import EvidenceStance


class Evidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence"

    atomic_claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("atomic_claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    passage_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    passage_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    start_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    end_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    retrieval_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    reranker_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    stance: Mapped[EvidenceStance | None] = mapped_column(
        SQLEnum(EvidenceStance, name="evidence_stance"),
        nullable=True,
        index=True,
    )

    stance_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    is_independent_source: Mapped[bool | None] = mapped_column(
        nullable=True,
    )

    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    atomic_claim = relationship(
        "AtomicClaim",
        back_populates="evidence_items",
    )

    document = relationship(
        "Document",
    )
