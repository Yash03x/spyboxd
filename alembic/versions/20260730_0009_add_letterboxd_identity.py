"""Add the canonical Letterboxd username to local app users.

Revision ID: 20260730_0009
Revises: 20260730_0008
Create Date: 2026-07-30 18:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0009"
down_revision: Union[str, None] = "20260730_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep this nullable for mixed-version deploys and legacy accounts. New
    # identities are required and validated by the application and Clerk.
    op.add_column(
        "app_users",
        sa.Column("letterboxd_username", sa.String(length=15), nullable=True),
    )
    op.add_column(
        "app_users",
        sa.Column(
            "primary_profile_required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    # Rows present at migration time are grandfathered. The server default stays
    # true so accounts inserted by either application version after this point
    # cannot bypass primary-profile onboarding during a mixed-version deploy.
    op.execute(
        sa.text(
            "UPDATE app_users SET primary_profile_required = false"
        )
    )
    op.create_index(
        "uq_app_users_letterboxd_username_lower",
        "app_users",
        [sa.text("lower(letterboxd_username)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_app_users_letterboxd_username_lower",
        table_name="app_users",
    )
    op.drop_column("app_users", "primary_profile_required")
    op.drop_column("app_users", "letterboxd_username")
