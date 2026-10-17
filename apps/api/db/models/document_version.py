"""Immutable snapshots of a document's retrieved contents."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class DocumentVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_version"
        ),
        CheckConstraint("version_number > 0", name="positive_version_number"),
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
    )

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    original_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at_snapshot: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document = relationship("Document")
