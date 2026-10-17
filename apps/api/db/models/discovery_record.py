"""Auditable results of provider discovery, without inventing full article bodies."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class DiscoveryRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "discovery_records"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "provider", "query_sha256", name="uq_discovery_doc_provider_query"
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    content_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    query_text: Mapped[str] = mapped_column(String(300), nullable=False)
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimant: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rating_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    claim_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
