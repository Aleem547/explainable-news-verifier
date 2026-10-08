"""Phase 9F: append-only cross-source passage diagnostics.

Revision ID: 9f52a1c840d6
Revises: 9e7c40b8f621
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9f52a1c840d6"
down_revision: str | None = "9e7c40b8f621"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cross_source_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("independence_assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_sha256", sa.String(64), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rule_version", sa.String(40), nullable=False),
        sa.Column("confidence_threshold", sa.Float(), nullable=False),
        sa.Column("input_count", sa.Integer(), nullable=False),
        sa.Column("decisive_count", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(48), nullable=False),
        sa.Column("independence_status", sa.String(40), nullable=False),
        sa.Column("supporting_families", postgresql.JSONB(), nullable=False),
        sa.Column("refuting_families", postgresql.JSONB(), nullable=False),
        sa.Column("mixed_families", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["independence_assessment_id"],
            ["independence_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(claim_sha256) = 64", name="ck_cross_source_assessments_claim_hash_length"
        ),
        sa.CheckConstraint(
            "confidence_threshold > 0 AND confidence_threshold <= 1",
            name="ck_cross_source_assessments_threshold_bounds",
        ),
        sa.CheckConstraint(
            "input_count BETWEEN 1 AND 100", name="ck_cross_source_assessments_input_count_bounds"
        ),
        sa.CheckConstraint(
            "decisive_count BETWEEN 0 AND input_count",
            name="ck_cross_source_assessments_decisive_count_bounds",
        ),
    )
    op.create_index(
        "ix_cross_source_assessments_independence_assessment_id",
        "cross_source_assessments",
        ["independence_assessment_id"],
    )
    op.create_index(
        "ix_cross_source_assessments_claim_sha256",
        "cross_source_assessments",
        ["claim_sha256"],
    )
    op.create_table(
        "cross_source_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_assessment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stance", sa.String(16), nullable=False),
        sa.Column("nli_confidence", sa.Float(), nullable=False),
        sa.Column("nli_accepted", sa.Boolean(), nullable=False),
        sa.Column("admissible", sa.Boolean(), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["cross_source_assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["passage_id"], ["document_passages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["context_assessment_id"], ["document_context_assessments.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("assessment_id", "passage_id", name="uq_cross_source_passage"),
        sa.CheckConstraint(
            "nli_confidence BETWEEN 0 AND 1", name="ck_cross_source_evidence_confidence_bounds"
        ),
        sa.CheckConstraint(
            "stance IN ('ENTAILMENT', 'CONTRADICTION', 'NEUTRAL')",
            name="ck_cross_source_evidence_valid_stance",
        ),
    )
    op.create_index(
        "ix_cross_source_evidence_assessment_id", "cross_source_evidence", ["assessment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_cross_source_evidence_assessment_id", table_name="cross_source_evidence")
    op.drop_table("cross_source_evidence")
    op.drop_index("ix_cross_source_assessments_claim_sha256", table_name="cross_source_assessments")
    op.drop_index(
        "ix_cross_source_assessments_independence_assessment_id",
        table_name="cross_source_assessments",
    )
    op.drop_table("cross_source_assessments")
