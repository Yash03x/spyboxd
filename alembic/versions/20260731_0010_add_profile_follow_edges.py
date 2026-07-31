"""Add the profile follow-edge table for the social graph.

One row per observed edge on a tracked profile's following/followers pages.
Counterparts are username-keyed with an opportunistic FK to canonical
profiles. The change-feed entity-type constraint widens to accept 'follow'
events; the new list is a strict superset, so existing rows all satisfy it.
The table is empty at migration time: each profile's first social sync
becomes its baseline and emits no change events.

Revision ID: 20260731_0010
Revises: 20260730_0009
Create Date: 2026-07-31 22:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260731_0010"
down_revision: Union[str, None] = "20260730_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENTITY_TYPES_LEGACY = "('film', 'watchlist', 'favorite', 'diary', 'review', 'list', 'list_item')"
_ENTITY_TYPES_WITH_FOLLOW = (
    "('film', 'watchlist', 'favorite', 'diary', 'review', 'list', 'list_item', 'follow')"
)


def upgrade() -> None:
    op.create_table(
        "profile_follow_edges",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("counterpart_username", sa.String(length=50), nullable=False),
        sa.Column("counterpart_username_normalized", sa.String(length=50), nullable=False),
        sa.Column("counterpart_display_name", sa.String(length=200), nullable=True),
        sa.Column("counterpart_avatar_url", sa.String(length=500), nullable=True),
        sa.Column("counterpart_profile_url", sa.String(length=500), nullable=True),
        sa.Column(
            "counterpart_profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=True),
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
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "profile_id",
            "direction",
            "counterpart_username_normalized",
            name="unique_profile_follow_edge",
        ),
        sa.CheckConstraint(
            "direction IN ('following', 'follower')",
            name="ck_profile_follow_edges_direction",
        ),
        sa.CheckConstraint(
            "position IS NULL OR position > 0",
            name="ck_profile_follow_edges_position_positive",
        ),
        sa.CheckConstraint(
            "counterpart_username_normalized = lower(counterpart_username_normalized)",
            name="ck_profile_follow_edges_normalized_lower",
        ),
    )
    op.create_index(
        "ix_profile_follow_edges_profile_removed",
        "profile_follow_edges",
        ["profile_id", "removed_at"],
    )
    op.create_index(
        "ix_profile_follow_edges_counterpart_active",
        "profile_follow_edges",
        ["counterpart_username_normalized", "direction", "profile_id"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "ix_profile_follow_edges_counterpart_profile",
        "profile_follow_edges",
        ["counterpart_profile_id"],
    )

    op.drop_constraint(
        "ck_profile_data_changes_entity_type",
        "profile_data_changes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_profile_data_changes_entity_type",
        "profile_data_changes",
        f"entity_type IN {_ENTITY_TYPES_WITH_FOLLOW}",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_profile_data_changes_entity_type",
        "profile_data_changes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_profile_data_changes_entity_type",
        "profile_data_changes",
        f"entity_type IN {_ENTITY_TYPES_LEGACY}",
    )
    op.drop_index("ix_profile_follow_edges_counterpart_profile", table_name="profile_follow_edges")
    op.drop_index("ix_profile_follow_edges_counterpart_active", table_name="profile_follow_edges")
    op.drop_index("ix_profile_follow_edges_profile_removed", table_name="profile_follow_edges")
    op.drop_table("profile_follow_edges")
