"""Phase 9E: append-only evidence reuse and source-independence assessments.

Revision ID: 9e7c40b8f621
Revises: 9d4ef081ac23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9e7c40b8f621"
down_revision: str | None = "9d4ef081ac23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "independence_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "assessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("rule_version", sa.String(40), nullable=False),
        sa.Column("snapshot_count", sa.Integer(), nullable=False),
        sa.Column("family_count", sa.Integer(), nullable=False),
        sa.Column("version_ids", postgresql.JSONB(), nullable=False),
        sa.Column("families", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "snapshot_count BETWEEN 2 AND 50",
            name="ck_independence_assessments_snapshot_count_bounds",
        ),
        sa.CheckConstraint(
            "family_count BETWEEN 1 AND snapshot_count",
            name="ck_independence_assessments_family_count_bounds",
        ),
    )
    op.create_table(
        "independence_pairs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("left_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("right_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship", sa.String(32), nullable=False),
        sa.Column("group_together", sa.Boolean(), nullable=False),
        sa.Column("basis", sa.String(100), nullable=False),
        sa.Column("signals", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["independence_assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["left_version_id"], ["document_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["right_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "assessment_id", "left_version_id", "right_version_id", name="uq_independence_pair"
        ),
        sa.CheckConstraint(
            "left_version_id <> right_version_id", name="ck_independence_pairs_distinct_versions"
        ),
        sa.CheckConstraint(
            "relationship IN ('SAME_PUBLISHER', 'DECLARED_COMMON_ORIGIN', "
            "'IDENTICAL_TEXT', 'POSSIBLE_TEXT_REUSE', 'UNDETERMINED')",
            name="ck_independence_pairs_valid_relationship",
        ),
    )
    op.create_index("ix_independence_pairs_assessment_id", "independence_pairs", ["assessment_id"])


def downgrade() -> None:
    op.drop_index("ix_independence_pairs_assessment_id", table_name="independence_pairs")
    op.drop_table("independence_pairs")
    op.drop_table("independence_assessments")
