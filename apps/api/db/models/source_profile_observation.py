"""Append-only source-profile observations; not a publisher trust rating."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class SourceProfileObservation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "source_profile_observations"
    __table_args__ = (
        CheckConstraint(
            "method IN ('PUBLISHER_PAGE', 'PROVIDER_METADATA', 'MANUAL_RECORD')",
            name="valid_method",
        ),
    )

    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    publisher_name_reported: Mapped[str | None] = mapped_column(String(255), nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    editorial_policy_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    corrections_policy_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ownership_disclosure_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
