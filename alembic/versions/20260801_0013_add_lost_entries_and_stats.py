"""Add lost entries (deleted/orphaned export history) and the stats snapshot.

Official exports ship deleted/ and orphaned/ folders: diary entries, reviews,
and comments whose target film or thread no longer resolves. They are history
the public profile cannot show, kept apart from live surfaces so they never
contaminate watch events, reviews, or film state.

profiles.stats_snapshot stores Letterboxd's own /<user>/stats/ header figures
(hours watched, distinct directors/countries, longest streak, multi-film days)
— values that cannot be derived from imported rows without full credit and
runtime metadata for every film.

Revision ID: 20260801_0013
Revises: 20260801_0012
Create Date: 2026-08-01 01:50:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260801_0013"
down_revision: Union[str, None] = "20260801_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("stats_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "profiles", sa.Column("stats_synced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "lost_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lost_kind", sa.String(length=10), nullable=False),
        sa.Column("entry_type", sa.String(length=10), nullable=False),
        sa.Column("entry_key", sa.String(length=600), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("watched_date", sa.Date(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column(
            "is_rewatch", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "first_seen_profile_sync_id",
            sa.BigInteger(),
            sa.ForeignKey("profile_syncs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_seen_profile_sync_id",
            sa.BigInteger(),
            sa.ForeignKey("profile_syncs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("profile_id", "entry_key", name="unique_lost_entry"),
        sa.CheckConstraint("lost_kind IN ('deleted', 'orphaned')", name="ck_lost_entries_kind"),
        sa.CheckConstraint(
            "entry_type IN ('diary', 'review', 'comment', 'list')",
            name="ck_lost_entries_type",
        ),
    )
    op.create_index(
        "ix_lost_entries_profile_kind",
        "lost_entries",
        ["profile_id", "lost_kind", "entry_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_lost_entries_profile_kind", table_name="lost_entries")
    op.drop_table("lost_entries")
    op.drop_column("profiles", "stats_synced_at")
    op.drop_column("profiles", "stats_snapshot")
