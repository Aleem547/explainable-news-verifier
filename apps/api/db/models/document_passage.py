"""Claim-independent passages linked to exact document snapshots."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class DocumentPassage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_passages"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal", name="uq_passage_version_ordinal"),
        CheckConstraint("ordinal >= 0", name="passage_ordinal_nonnegative"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="passage_offsets"),
        CheckConstraint("length(passage_sha256) = 64", name="passage_sha256_length"),
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    passage_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
