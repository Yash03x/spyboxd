"""Keep the rating histogram's ten buckets, not just its average.

The rating-histogram include already returns every half-star bucket and the
parser already reads them; only the weighted average was persisted. Storing
the shape lets a rating be placed against the crowd ("in the 2% who rated it
half a star") rather than merely above or below the mean, and costs no extra
requests.

Revision ID: 20260801_0016
Revises: 20260801_0015
Create Date: 2026-08-01 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260801_0016"
down_revision: Union[str, None] = "20260801_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movies",
        sa.Column(
            "letterboxd_rating_distribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("movies", "letterboxd_rating_distribution")
