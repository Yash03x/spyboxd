"""Add RSS rolling-window reconciliation state.

Revision ID: 20260729_0006
Revises: 20260729_0005
Create Date: 2026-07-29 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260729_0006"
down_revision: Union[str, None] = "20260729_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profile_feed_states",
        sa.Column(
            "activity_guids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "profile_feed_states",
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "profile_feed_states",
        sa.Column(
            "requires_full_sync",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "profile_feed_states",
        sa.Column("reconciliation_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("profile_feed_states", "reconciliation_reason")
    op.drop_column("profile_feed_states", "requires_full_sync")
    op.drop_column("profile_feed_states", "last_changed_at")
    op.drop_column("profile_feed_states", "activity_guids")
