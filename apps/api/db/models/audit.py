from __future__ import annotations

from uuid import UUID

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from apps.api.db.enums import ActorType


class AuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_events"

    event_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    entity_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    entity_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        index=True,
    )

    actor_type: Mapped[ActorType] = mapped_column(
        SQLEnum(ActorType, name="actor_type"),
        default=ActorType.SYSTEM,
        nullable=False,
    )

    actor_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    details: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
