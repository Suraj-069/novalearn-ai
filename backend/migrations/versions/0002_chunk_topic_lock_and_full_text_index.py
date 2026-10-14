"""chunk topic lock and full text index

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13 04:04:42.268511
"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default keeps existing rows valid
    op.add_column("content_chunks", sa.Column("topic_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("conversation_messages", sa.Column("mode", sa.String(length=12), nullable=True))
    # Full-text index backing keyword retrieval (PostgreSQL only; the query uses the same expression)
    op.execute("CREATE INDEX ix_content_chunks_fts ON content_chunks USING gin (to_tsvector('english', text))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_content_chunks_fts")
    op.drop_column("conversation_messages", "mode")
    op.drop_column("content_chunks", "topic_locked")
