"""Add conservative Letterboxd RSS poll state.

Revision ID: 20260729_0005
Revises: 20260729_0004
Create Date: 2026-07-29 14:00:00

The feed state is operational metadata only.  Authoritative profile history
continues to come from a full HTML or owner-export sync.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0005"
down_revision: Union[str, None] = "20260729_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_feed_states",
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("feed_url", sa.String(length=500), nullable=False),
        sa.Column("etag", sa.String(length=500), nullable=True),
        sa.Column("last_modified", sa.String(length=200), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("latest_item_guid", sa.String(length=200), nullable=True),
        sa.Column(
            "latest_item_published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
            "consecutive_failures >= 0",
            name="ck_profile_feed_states_failures_nonnegative",
        ),
        sa.CheckConstraint(
            "last_http_status IS NULL OR (last_http_status >= 100 AND last_http_status <= 599)",
            name="ck_profile_feed_states_http_status",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    op.create_index(
        "ix_profile_feed_states_next_poll",
        "profile_feed_states",
        ["next_poll_at", "profile_id"],
    )
    op.create_index(
        "ix_profile_feed_states_lease",
        "profile_feed_states",
        ["lease_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_feed_states_lease", table_name="profile_feed_states")
    op.drop_index(
        "ix_profile_feed_states_next_poll",
        table_name="profile_feed_states",
    )
    op.drop_table("profile_feed_states")
