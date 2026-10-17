"""Durable index preparation queue, not a claim that Qdrant indexing has happened."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class IndexOutbox(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "index_outbox"
    __table_args__ = (
        UniqueConstraint("document_version_id", "index_name", name="uq_outbox_version_index"),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETE', 'FAILED')",
            name="index_status",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    index_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
