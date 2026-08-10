"""Three values the panels read out of raw_payload, promoted to columns.

`raw_payload` holds the whole TMDB response including watch providers. The film
query never selected it -- that mistake was made once and took the API down --
and instead extracted three values from it by JSON path.

That is still expensive, for a reason the JSON path does not make obvious:
Postgres has to detoast the whole payload to read any part of it. Behind one
profile's library that is 39MB, and once `credits` stopped being the bottleneck
(20260810_0019) these three paths were 65% of what the query cost.

So they become columns. `raw_payload` stays exactly as it is -- the record of
what TMDB returned -- and these are the derived read-path copies, the same
arrangement `genres` and `production_countries` already have.

`belongs_to_collection` becomes `collection_name` rather than a JSON copy: the
only thing read from it is the franchise name.

Column only. Filling it is `scripts/backfill_credits_summary.py`, resumable and
paced, for the same reason as the last one: this database is live and rewriting
every enrichment row holds a lock for the length of the rewrite. Readers fall
back to the payload while a row is NULL, so the deploy is safe in either order.

Revision ID: 20260810_0020
Revises: 20260810_0019
Create Date: 2026-08-10 04:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260810_0020"
down_revision: Union[str, None] = "20260810_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movie_enrichments",
        sa.Column("production_companies", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "movie_enrichments",
        sa.Column("spoken_languages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "movie_enrichments",
        sa.Column("collection_name", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("movie_enrichments", "collection_name")
    op.drop_column("movie_enrichments", "spoken_languages")
    op.drop_column("movie_enrichments", "production_companies")
