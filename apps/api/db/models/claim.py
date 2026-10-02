from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from apps.api.db.enums import ClaimStatus

if TYPE_CHECKING:
    from apps.api.db.models.document import Document
    from apps.api.db.models.evidence import Evidence
    from apps.api.db.models.verification import VerificationResult


class Claim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claims"

    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    normalized_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    claim_hash: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
        nullable=True,
    )

    language: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    status: Mapped[ClaimStatus] = mapped_column(
        SQLEnum(ClaimStatus, name="claim_status"),
        default=ClaimStatus.PENDING,
        nullable=False,
        index=True,
    )

    extraction_model: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    document: Mapped[Document | None] = relationship(
        back_populates="claims",
    )

    atomic_claims: Mapped[list[AtomicClaim]] = relationship(
        back_populates="parent_claim",
        cascade="all, delete-orphan",
    )


class AtomicClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "atomic_claims"

    parent_claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    normalized_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    parent_claim: Mapped[Claim] = relationship(
        back_populates="atomic_claims",
    )

    evidence_items: Mapped[list[Evidence]] = relationship(
        back_populates="atomic_claim",
        cascade="all, delete-orphan",
    )

    verification_results: Mapped[list[VerificationResult]] = relationship(
        back_populates="atomic_claim",
        cascade="all, delete-orphan",
    )
