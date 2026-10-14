"""question verification details and attempt metadata

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("verification", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("questions", sa.Column("generation_method", sa.String(length=12), nullable=False, server_default="cloze"))
    op.add_column("assessment_attempts", sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("assessment_attempts", "meta")
    op.drop_column("questions", "generation_method")
    op.drop_column("questions", "verification")
