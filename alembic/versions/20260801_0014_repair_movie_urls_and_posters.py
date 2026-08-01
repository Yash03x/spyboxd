"""Repair site-relative movie URLs and placeholder posters.

Letterboxd's markup carries site-relative hrefs (``/film/<slug>/``) and lazy
loads posters, so a scraped ``img src`` is their static empty-poster asset.
Both were persisted verbatim: relative URLs rendered as in-app links, and the
placeholder occupied ``poster_url``, which blocked TMDB enrichment from ever
filling in real artwork (it only wrote when the column was empty).

Existing rows are repaired here; the resolver now normalises URLs and rejects
placeholder posters so new imports cannot reintroduce either. Clearing a
placeholder lets the next enrichment pass populate the real poster, and rows
that already hold a TMDB poster are left untouched.

Revision ID: 20260801_0014
Revises: 20260801_0013
Create Date: 2026-08-01 02:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260801_0014"
down_revision: Union[str, None] = "20260801_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A member can list several external links (personal site, Twitter, …);
    # only one ever had a home.
    op.add_column(
        "profiles",
        sa.Column("external_links", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Site-relative film links become absolute Letterboxd URLs.
    op.execute(
        sa.text(
            """
            UPDATE movies
               SET letterboxd_url = 'https://letterboxd.com' || letterboxd_url
             WHERE letterboxd_url LIKE '/%'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE movies
               SET poster_url = NULL
             WHERE poster_url LIKE '%empty-poster%'
            """
        )
    )
    # Backfill from enrichment we already hold, so repaired rows show real
    # artwork immediately instead of waiting for the next TMDB pass.
    op.execute(
        sa.text(
            """
            UPDATE movies
               SET poster_url = 'https://image.tmdb.org/t/p/w500' || e.poster_path
              FROM movie_enrichments AS e
             WHERE e.movie_id = movies.id
               AND movies.poster_url IS NULL
               AND e.poster_path IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("profiles", "external_links")
    # The data repair itself is not reversible: the original values were
    # malformed, and restoring them would reintroduce broken links and
    # placeholder posters.
