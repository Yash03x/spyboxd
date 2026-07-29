"""Cache deferred TMDB identity lookups.

Revision ID: 20260729_0007
Revises: 20260729_0006
Create Date: 2026-07-29 20:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0007"
down_revision: Union[str, None] = "20260729_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movies",
        sa.Column("tmdb_lookup_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "movies",
        sa.Column("tmdb_lookup_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "movies",
        sa.Column("tmdb_lookup_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_movies_tmdb_lookup_expires_at",
        "movies",
        ["tmdb_lookup_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_movies_tmdb_lookup_expires_at", table_name="movies")
    op.drop_column("movies", "tmdb_lookup_key")
    op.drop_column("movies", "tmdb_lookup_expires_at")
    op.drop_column("movies", "tmdb_lookup_attempted_at")
