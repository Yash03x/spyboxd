"""Add the Letterboxd completeness columns.

- profiles.letterboxd_person_id: the stable numeric member id (survives
  username renames; uploads under an unknown username can be recognized and
  renamed in place instead of duplicated), with a unique index.
- profiles.member_badge, profiles.reported_watchlist_count: profile header
  facts the scraper can observe (the watchlist count matters most when the
  watchlist itself is private).
- watch_events.logged_date: official exports carry both the log date and the
  watch date; previously the log date was discarded.
- movie_lists.updated_date: list detail pages expose the last-updated
  timestamp next to the published one.

All additive and nullable; every column stays NULL until a source observes it.

Revision ID: 20260731_0011
Revises: 20260731_0010
Create Date: 2026-07-31 23:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260731_0011"
down_revision: Union[str, None] = "20260731_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("letterboxd_person_id", sa.BigInteger(), nullable=True))
    op.add_column("profiles", sa.Column("member_badge", sa.String(length=20), nullable=True))
    op.add_column(
        "profiles", sa.Column("reported_watchlist_count", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_profiles_reported_watchlist_nonnegative",
        "profiles",
        "reported_watchlist_count IS NULL OR reported_watchlist_count >= 0",
    )
    op.create_index(
        "uq_profiles_letterboxd_person_id",
        "profiles",
        ["letterboxd_person_id"],
        unique=True,
    )
    op.add_column("watch_events", sa.Column("logged_date", sa.Date(), nullable=True))
    op.add_column("movie_lists", sa.Column("updated_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("movie_lists", "updated_date")
    op.drop_column("watch_events", "logged_date")
    op.drop_index("uq_profiles_letterboxd_person_id", table_name="profiles")
    op.drop_constraint(
        "ck_profiles_reported_watchlist_nonnegative", "profiles", type_="check"
    )
    op.drop_column("profiles", "reported_watchlist_count")
    op.drop_column("profiles", "member_badge")
    op.drop_column("profiles", "letterboxd_person_id")
