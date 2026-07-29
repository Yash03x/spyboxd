"""Add profile change history and explicit non-watch source activity.

Revision ID: 20260729_0004
Revises: 20260728_0003
Create Date: 2026-07-29 12:00:00

The change feed is additive and empty at migration time. Existing profile
snapshots become the baseline; only later successful syncs append deltas.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260729_0004"
down_revision: Union[str, None] = "20260728_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JSONB_EMPTY_OBJECT = sa.text("'{}'::jsonb")
JSONB_EMPTY_ARRAY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSONB_EMPTY_ARRAY,
            nullable=False,
        ),
    )
    op.add_column(
        "movie_lists",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSONB_EMPTY_ARRAY,
            nullable=False,
        ),
    )
    op.add_column(
        "watchlist_items",
        sa.Column("added_date_source_kind", sa.String(length=50), nullable=True),
    )

    op.create_table(
        "profile_data_changes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("profile_sync_id", sa.BigInteger(), nullable=False),
        sa.Column("change_key", sa.String(length=600), nullable=False),
        sa.Column("change_type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_key", sa.String(length=600), nullable=False),
        sa.Column("source_kind", sa.String(length=50), nullable=False),
        sa.Column("source_dataset", sa.String(length=50), nullable=True),
        sa.Column("movie_id", sa.BigInteger(), nullable=True),
        sa.Column("movie_list_id", sa.Integer(), nullable=True),
        sa.Column(
            "before",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSONB_EMPTY_OBJECT,
            nullable=False,
        ),
        sa.Column(
            "after",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSONB_EMPTY_OBJECT,
            nullable=False,
        ),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('film', 'watchlist', 'favorite', 'diary', 'review', 'list', 'list_item')",
            name="ck_profile_data_changes_entity_type",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_sync_id"], ["profile_syncs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["movie_list_id"], ["movie_lists.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_sync_id",
            "change_key",
            name="unique_profile_sync_change_key",
        ),
    )
    op.create_index(
        "ix_profile_data_changes_detected",
        "profile_data_changes",
        ["detected_at", "id"],
    )
    op.create_index(
        "ix_profile_data_changes_profile_detected",
        "profile_data_changes",
        ["profile_id", "detected_at"],
    )

    op.create_table(
        "profile_source_activities",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_key", sa.String(length=600), nullable=False),
        sa.Column("activity_type", sa.String(length=50), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("date_semantics", sa.String(length=50), nullable=False),
        sa.Column("source_kind", sa.String(length=50), nullable=False),
        sa.Column("source_dataset", sa.String(length=50), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "activity_type IN ('watched_marked', 'rating_recorded', 'like_recorded', 'watchlist_added')",
            name="ck_profile_source_activities_type",
        ),
        sa.CheckConstraint(
            "date_semantics IN ('account_activity', 'watchlist_added')",
            name="ck_profile_source_activities_date_semantics",
        ),
        sa.CheckConstraint(
            "source_row_number IS NULL OR source_row_number > 0",
            name="ck_profile_source_activities_row_positive",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["first_seen_profile_sync_id"],
            ["profile_syncs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_profile_sync_id"],
            ["profile_syncs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "activity_key",
            name="unique_profile_source_activity",
        ),
    )
    op.create_index(
        "ix_profile_source_activities_profile_date",
        "profile_source_activities",
        ["profile_id", "activity_date"],
    )
    op.create_index(
        "ix_profile_source_activities_movie_date",
        "profile_source_activities",
        ["movie_id", "activity_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_profile_source_activities_movie_date",
        table_name="profile_source_activities",
    )
    op.drop_index(
        "ix_profile_source_activities_profile_date",
        table_name="profile_source_activities",
    )
    op.drop_table("profile_source_activities")

    op.drop_index(
        "ix_profile_data_changes_profile_detected",
        table_name="profile_data_changes",
    )
    op.drop_index("ix_profile_data_changes_detected", table_name="profile_data_changes")
    op.drop_table("profile_data_changes")

    op.drop_column("watchlist_items", "added_date_source_kind")
    op.drop_column("movie_lists", "tags")
    op.drop_column("reviews", "tags")
