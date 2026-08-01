"""Add Letterboxd's own crowd rating per film.

Letterboxd publishes a weighted average and rating count for every film on
its rating-histogram include. The figure is film-level and shared by every
profile, so one fetch serves the whole library and belongs on ``movies``
rather than on any per-profile row.

Revision ID: 20260801_0015
Revises: 20260801_0014
Create Date: 2026-08-01 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0015"
down_revision: Union[str, None] = "20260801_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("movies", sa.Column("letterboxd_average_rating", sa.Float(), nullable=True))
    op.add_column("movies", sa.Column("letterboxd_rating_count", sa.BigInteger(), nullable=True))
    op.add_column(
        "movies",
        sa.Column("letterboxd_rating_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_movies_letterboxd_average_range",
        "movies",
        "letterboxd_average_rating IS NULL "
        "OR (letterboxd_average_rating >= 0 AND letterboxd_average_rating <= 5)",
    )
    op.create_check_constraint(
        "ck_movies_letterboxd_rating_count_nonnegative",
        "movies",
        "letterboxd_rating_count IS NULL OR letterboxd_rating_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_movies_letterboxd_rating_count_nonnegative", "movies", type_="check")
    op.drop_constraint("ck_movies_letterboxd_average_range", "movies", type_="check")
    op.drop_column("movies", "letterboxd_rating_synced_at")
    op.drop_column("movies", "letterboxd_rating_count")
    op.drop_column("movies", "letterboxd_average_rating")
