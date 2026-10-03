"""Public anime metadata, separate from immutable personal imports.

Revision ID: 20261003_0022
Revises: 20261003_0021
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261003_0022"
down_revision = "20261003_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "anime_metadata_cache",
        sa.Column("mal_id", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(255)),
    )


def downgrade():
    op.drop_table("anime_metadata_cache")
