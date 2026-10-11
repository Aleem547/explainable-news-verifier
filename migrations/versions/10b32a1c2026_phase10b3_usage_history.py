"""Phase 10B3.2: durable pseudonymous verification usage history.

Revision ID: 10b32a1c2026
Revises: 9f52a1c840d6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10b32a1c2026"
down_revision: str | None = "9f52a1c840d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_usage_events",
        sa.Column("request_id", sa.String(24), primary_key=True, nullable=False),
        sa.Column("actor_fingerprint", sa.String(24), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status_code", sa.SmallInteger(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "status_code BETWEEN 100 AND 599", name="ck_verification_usage_events_status_code_range"
        ),
        sa.CheckConstraint(
            "latency_ms >= 0", name="ck_verification_usage_events_latency_nonnegative"
        ),
    )
    op.create_index(
        "ix_verification_usage_actor_time",
        "verification_usage_events",
        ["actor_fingerprint", "occurred_at"],
    )
    op.create_index(
        "ix_verification_usage_occurred_at",
        "verification_usage_events",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_verification_usage_occurred_at", table_name="verification_usage_events")
    op.drop_index("ix_verification_usage_actor_time", table_name="verification_usage_events")
    op.drop_table("verification_usage_events")
