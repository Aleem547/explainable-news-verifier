"""Phase 9C: discovery provenance, snapshot passages and index outbox.

Revision ID: 9c36be16d992
Revises: 9a16d02cbe34
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c36be16d992"
down_revision: str | None = "9a16d02cbe34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("content_kind", sa.String(32), nullable=False),
        sa.Column("query_text", sa.String(300), nullable=False),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("matched_claim", sa.Text(), nullable=True),
        sa.Column("claimant", sa.String(500), nullable=True),
        sa.Column("rating_text", sa.String(200), nullable=True),
        sa.Column("claim_date", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id", "provider", "query_sha256", name="uq_discovery_doc_provider_query"
        ),
    )
    op.create_index("ix_discovery_records_document_id", "discovery_records", ["document_id"])

    op.create_table(
        "document_passages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("passage_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("document_version_id", "ordinal", name="uq_passage_version_ordinal"),
        sa.CheckConstraint("ordinal >= 0", name="ck_document_passages_passage_ordinal_nonnegative"),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_document_passages_passage_offsets",
        ),
        sa.CheckConstraint(
            "length(passage_sha256) = 64", name="ck_document_passages_passage_sha256_length"
        ),
    )
    op.create_index(
        "ix_document_passages_document_version_id", "document_passages", ["document_version_id"]
    )
    op.create_index("ix_document_passages_passage_sha256", "document_passages", ["passage_sha256"])

    op.create_table(
        "index_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("document_version_id", "index_name", name="uq_outbox_version_index"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETE', 'FAILED')",
            name="ck_index_outbox_index_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_index_outbox_attempts_nonnegative"),
    )
    op.create_index("ix_index_outbox_document_version_id", "index_outbox", ["document_version_id"])


def downgrade() -> None:
    op.drop_index("ix_index_outbox_document_version_id", table_name="index_outbox")
    op.drop_table("index_outbox")
    op.drop_index("ix_document_passages_passage_sha256", table_name="document_passages")
    op.drop_index("ix_document_passages_document_version_id", table_name="document_passages")
    op.drop_table("document_passages")
    op.drop_index("ix_discovery_records_document_id", table_name="discovery_records")
    op.drop_table("discovery_records")
