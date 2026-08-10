"""The part of a credits document the panels actually read.

`movie_enrichments.credits` is the whole TMDB credits payload: a hundred-plus
crew entries and forty cast, each carrying profile_path, credit_id, popularity
and known_for_department. It averages 22KB a film.

Every panel that touches it reads three things — names, job titles, and the
gender of directors. Loading one profile's library therefore shipped 36MB of
JSON to use about a sixth of it, which is what made the profile stats panel
take seven seconds against production data while every test passed. Measured on
the real table: `credits` was 89% of that query's cost, and the summary is 84%
smaller.

This migration only adds the column. Filling it is `scripts/backfill_credits_summary.py`,
which is resumable and paced -- a migration that rewrites every enrichment row
would hold a lock for the length of the rewrite, and this database is live.
Until a row is filled the column is NULL and readers fall back to `credits`, so
the deploy is safe in either order.

`credits` itself is kept. It stays the record of what TMDB actually said; this
is a derived read-path column, not a replacement.

Revision ID: 20260810_0019
Revises: 20260809_0018
Create Date: 2026-08-10 03:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260810_0019"
down_revision: Union[str, None] = "20260809_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable with no server default: NULL means "not summarised yet", which
    # is what the reader's fallback keys off. A default of '{}' would be
    # indistinguishable from a film whose credits are genuinely empty, and the
    # reader would serve empty crew rather than falling back.
    # JSONB, matching the model's `_json_type()` — every other JSON column here
    # is JSONB on Postgres, and CI's autogenerate drift check compares against
    # the model rather than taking the migration's word for it.
    op.add_column(
        "movie_enrichments",
        sa.Column("credits_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("movie_enrichments", "credits_summary")
