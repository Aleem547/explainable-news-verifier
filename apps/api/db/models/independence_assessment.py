"""Append-only evidence-family assessment; families are not verified sources."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class IndependenceAssessment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "independence_assessments"
    __table_args__ = (
        CheckConstraint("snapshot_count BETWEEN 2 AND 50", name="snapshot_count_bounds"),
        CheckConstraint("family_count BETWEEN 1 AND snapshot_count", name="family_count_bounds"),
    )

    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    snapshot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    family_count: Mapped[int] = mapped_column(Integer, nullable=False)
    version_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    families: Mapped[list[list[str]]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
