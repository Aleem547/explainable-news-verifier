"""Add PostgreSQL full-text GIN index for article passages.

Revision ID: f13f2d8gin20261024
Revises: 10b32a1c2026
"""

from alembic import op
from sqlalchemy import text

revision = "f13f2d8gin20261024"
down_revision = "10b32a1c2026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_document_passages_text_fts",
        "document_passages",
        [text("to_tsvector('english'::regconfig, text)")],
        schema="public",
        unique=False,
        postgresql_using="gin",
    )


def downgrade():
    op.drop_index(
        "ix_document_passages_text_fts",
        table_name="document_passages",
        schema="public",
    )
