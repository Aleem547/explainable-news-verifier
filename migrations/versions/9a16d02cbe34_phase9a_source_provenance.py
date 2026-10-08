"""phase 9a additive external-document provenance schema

Revision ID: 9a16d02cbe34
Revises: 5014402fb40f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a16d02cbe34"
down_revision: str | Sequence[str] | None = "5014402fb40f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add provenance without altering the legacy source/document/evidence tables."""
    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("original_url", sa.String(length=2048), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("published_at_snapshot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number > 0", name=op.f("ck_document_versions_positive_version_number")
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name=op.f("ck_document_versions_sha256_length")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_version"
        ),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_content_sha256", "document_versions", ["content_sha256"])

    op.create_table(
        "retrieval_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("requested_url", sa.String(length=2048), nullable=False),
        sa.Column("final_url", sa.String(length=2048), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("etag", sa.String(length=512), nullable=True),
        sa.Column("last_modified_header", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('FETCHED', 'NOT_MODIFIED', 'HTTP_ERROR', 'NETWORK_ERROR')",
            name=op.f("ck_retrieval_observations_valid_outcome"),
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR (http_status BETWEEN 100 AND 599)",
            name=op.f("ck_retrieval_observations_valid_http_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_retrieval_observations_source_id_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_retrieval_observations_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_retrieval_observations_document_version_id_document_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_observations")),
    )
    for column in ("source_id", "document_id", "document_version_id", "observed_at"):
        op.create_index(f"ix_retrieval_observations_{column}", "retrieval_observations", [column])

    op.create_table(
        "evidence_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_url", sa.String(length=2048), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.Column("locator_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name=op.f("fk_evidence_provenance_evidence_id_evidence"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_evidence_provenance_document_version_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["retrieval_observations.id"],
            name=op.f("fk_evidence_provenance_observation_id_retrieval_observations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_provenance")),
        sa.UniqueConstraint("evidence_id", name="uq_evidence_provenance_evidence_id"),
    )
    op.create_index(
        "ix_evidence_provenance_document_version_id", "evidence_provenance", ["document_version_id"]
    )
    op.create_index(
        "ix_evidence_provenance_observation_id", "evidence_provenance", ["observation_id"]
    )


def downgrade() -> None:
    """Drop only Phase 9A tables; never modify legacy tables."""
    op.drop_index("ix_evidence_provenance_observation_id", table_name="evidence_provenance")
    op.drop_index("ix_evidence_provenance_document_version_id", table_name="evidence_provenance")
    op.drop_table("evidence_provenance")

    for column in ("observed_at", "document_version_id", "document_id", "source_id"):
        op.drop_index(f"ix_retrieval_observations_{column}", table_name="retrieval_observations")
    op.drop_table("retrieval_observations")

    op.drop_index("ix_document_versions_content_sha256", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
