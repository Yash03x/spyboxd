"""Store who wrote the thing a member liked, not just its short link.

`member_content_likes` records a `boxd.it` short URL and a date, which is all
an official export gives. The link redirects to the full path, and that path
carries both the author and the film -- `boxd.it/fwSSUD` resolves to
`letterboxd.com/deathproof/film/spider-man-brand-new-day/`.

Without resolving it a like is an opaque token, and 46 of them render as the
number 46. Resolved, they say whose writing somebody actually rates: 12 of one
profile's 44 liked reviews are by a single tracked member, against 2 for the
next most-liked author.

Resolution is stored rather than repeated because it costs one HTTP request per
like against a rate-limited host.

Revision ID: 20260802_0017
Revises: 20260801_0016
Create Date: 2026-08-02 17:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260802_0017"
down_revision: Union[str, None] = "20260801_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable throughout: an unresolved like is a real state, and a link that
    # 404s or points at something other than a member's page must stay null
    # rather than be guessed at.
    op.add_column(
        "member_content_likes",
        sa.Column("target_username", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "member_content_likes",
        sa.Column("target_film_slug", sa.String(length=250), nullable=True),
    )
    op.add_column(
        "member_content_likes",
        sa.Column(
            "target_resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_member_content_likes_target_username",
        "member_content_likes",
        ["target_username"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_member_content_likes_target_username",
        table_name="member_content_likes",
    )
    op.drop_column("member_content_likes", "target_resolved_at")
    op.drop_column("member_content_likes", "target_film_slug")
    op.drop_column("member_content_likes", "target_username")
