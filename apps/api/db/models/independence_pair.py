"""Pairs of exact document snapshots checked for potential shared origin."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, UUIDPrimaryKeyMixin


class IndependencePair(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "independence_pairs"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "left_version_id", "right_version_id", name="uq_independence_pair"
        ),
        CheckConstraint("left_version_id <> right_version_id", name="distinct_versions"),
        CheckConstraint(
            "relationship IN ('SAME_PUBLISHER', 'DECLARED_COMMON_ORIGIN', "
            "'IDENTICAL_TEXT', 'POSSIBLE_TEXT_REUSE', 'UNDETERMINED')",
            name="valid_relationship",
        ),
    )

    assessment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("independence_assessments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    left_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    right_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    relationship: Mapped[str] = mapped_column(String(32), nullable=False)
    group_together: Mapped[bool] = mapped_column(Boolean, nullable=False)
    basis: Mapped[str] = mapped_column(String(100), nullable=False)
    signals: Mapped[dict[str, float | None]] = mapped_column(JSONB, nullable=False)
