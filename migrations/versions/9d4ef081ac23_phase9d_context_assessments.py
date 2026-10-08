"""Phase 9D: append-only source profile and temporal context observations.

Revision ID: 9d4ef081ac23
Revises: 9c36be16d992
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9d4ef081ac23"
down_revision: str | None = "9c36be16d992"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_profile_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("observed_url", sa.String(2048), nullable=True),
        sa.Column("publisher_name_reported", sa.String(255), nullable=True),
        sa.Column("homepage_url", sa.String(2048), nullable=True),
        sa.Column("editorial_policy_url", sa.String(2048), nullable=True),
        sa.Column("corrections_policy_url", sa.String(2048), nullable=True),
        sa.Column("ownership_disclosure_url", sa.String(2048), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "method IN ('PUBLISHER_PAGE', 'PROVIDER_METADATA', 'MANUAL_RECORD')",
            name="ck_source_profile_observations_valid_method",
        ),
    )
    op.create_index(
        "ix_source_profile_observations_source_id", "source_profile_observations", ["source_id"]
    )
    op.create_index(
        "ix_source_profile_observations_observed_at", "source_profile_observations", ["observed_at"]
    )

    op.create_table(
        "document_context_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_profile_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retrieval_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim_sha256", sa.String(64), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_age_days", sa.Integer(), nullable=True),
        sa.Column("temporal_relation", sa.String(32), nullable=False),
        sa.Column("freshness_status", sa.String(32), nullable=False),
        sa.Column("metadata_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_profile_observation_id"],
            ["source_profile_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_observation_id"], ["retrieval_observations.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "temporal_relation IN ('BEFORE_REFERENCE', 'SAME_REFERENCE_DAY', "
            "'AFTER_REFERENCE', 'UNKNOWN')",
            name="ck_document_context_assessments_valid_temporal_relation",
        ),
        sa.CheckConstraint(
            "freshness_status IN ('NOT_REQUESTED', 'UNKNOWN', 'WITHIN_WINDOW', "
            "'OLDER_THAN_WINDOW', 'FUTURE_DATED')",
            name="ck_document_context_assessments_valid_freshness_status",
        ),
        sa.CheckConstraint(
            "max_age_days IS NULL OR max_age_days BETWEEN 1 AND 36500",
            name="ck_document_context_assessments_valid_max_age_days",
        ),
    )
    op.create_index(
        "ix_document_context_assessments_document_version_id",
        "document_context_assessments",
        ["document_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_context_assessments_document_version_id",
        table_name="document_context_assessments",
    )
    op.drop_table("document_context_assessments")
    op.drop_index(
        "ix_source_profile_observations_observed_at", table_name="source_profile_observations"
    )
    op.drop_index(
        "ix_source_profile_observations_source_id", table_name="source_profile_observations"
    )
    op.drop_table("source_profile_observations")
