"""Add Clerk users, tracked profiles, and profile access requests.

Revision ID: 20260730_0008
Revises: 20260729_0007
Create Date: 2026-07-30 00:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0008"
down_revision: Union[str, None] = "20260729_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_keys = bind.execute(
        sa.text(
            """
            SELECT lower(username) AS normalized_username
            FROM profiles
            GROUP BY lower(username)
            HAVING count(*) > 1
            LIMIT 20
            """
        )
    ).scalars().all()
    if duplicate_keys:
        duplicate_usernames = {
            normalized: bind.execute(
                sa.text(
                    """
                    SELECT username
                    FROM profiles
                    WHERE lower(username) = :normalized
                    ORDER BY username
                    """
                ),
                {"normalized": normalized},
            ).scalars().all()
            for normalized in duplicate_keys
        }
        collisions = "; ".join(
            f"{normalized}: {', '.join(usernames)}"
            for normalized, usernames in duplicate_usernames.items()
        )
        raise RuntimeError(
            "Cannot enforce case-insensitive profile usernames; resolve these "
            f"collisions first: {collisions}"
        )

    op.create_index(
        "uq_profiles_username_lower",
        "profiles",
        [sa.text("lower(username)")],
        unique=True,
    )

    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clerk_user_id", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_users_id", "app_users", ["id"], unique=False)
    op.create_index(
        "ix_app_users_clerk_user_id",
        "app_users",
        ["clerk_user_id"],
        unique=True,
    )

    op.create_table(
        "user_tracked_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), server_default="direct", nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('direct', 'request_fulfillment', 'admin')",
            name="ck_user_tracked_profiles_source",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "profile_id", name="uq_user_tracked_profile"),
    )
    op.create_index(
        "ix_user_tracked_profiles_id",
        "user_tracked_profiles",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_user_tracked_profiles_profile_user",
        "user_tracked_profiles",
        ["profile_id", "user_id"],
        unique=False,
    )

    op.create_table(
        "profile_access_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("requested_username", sa.String(length=50), nullable=False),
        sa.Column("normalized_username", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_clerk_user_id", sa.String(length=255), nullable=True),
        sa.Column("fulfilled_profile_id", sa.Integer(), nullable=True),
        sa.Column(
            "requested_at",
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
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'fulfilled')",
            name="ck_profile_access_requests_status",
        ),
        sa.ForeignKeyConstraint(
            ["fulfilled_profile_id"],
            ["profiles.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "normalized_username",
            name="uq_profile_access_request_user_username",
        ),
    )
    op.create_index(
        "ix_profile_access_requests_id",
        "profile_access_requests",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_profile_access_requests_status_requested",
        "profile_access_requests",
        ["status", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_profile_access_requests_username_status",
        "profile_access_requests",
        ["normalized_username", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_profile_access_requests_username_status",
        table_name="profile_access_requests",
    )
    op.drop_index(
        "ix_profile_access_requests_status_requested",
        table_name="profile_access_requests",
    )
    op.drop_index("ix_profile_access_requests_id", table_name="profile_access_requests")
    op.drop_table("profile_access_requests")
    op.drop_index(
        "ix_user_tracked_profiles_profile_user",
        table_name="user_tracked_profiles",
    )
    op.drop_index("ix_user_tracked_profiles_id", table_name="user_tracked_profiles")
    op.drop_table("user_tracked_profiles")
    op.drop_index("ix_app_users_clerk_user_id", table_name="app_users")
    op.drop_index("ix_app_users_id", table_name="app_users")
    op.drop_table("app_users")
    op.drop_index("uq_profiles_username_lower", table_name="profiles")
