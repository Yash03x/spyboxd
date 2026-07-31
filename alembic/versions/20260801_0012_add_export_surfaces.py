"""Add the export-only member surfaces.

Official account exports (the only source) carry three surfaces the runtime
previously read and dropped: likes/reviews.csv and likes/lists.csv (like date
plus the boxd.it URL of the liked content) and comments.csv (date, target URL,
comment HTML). profiles.pronoun comes from the export's profile.csv.

Revision ID: 20260801_0012
Revises: 20260731_0011
Create Date: 2026-08-01 00:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0012"
down_revision: Union[str, None] = "20260731_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("pronoun", sa.String(length=50), nullable=True))
    op.create_table(
        "member_content_likes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_type", sa.String(length=10), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=False),
        sa.Column("liked_date", sa.Date(), nullable=True),
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "profile_id", "content_type", "target_url", name="unique_member_content_like"
        ),
        sa.CheckConstraint(
            "content_type IN ('review', 'list')", name="ck_member_content_likes_type"
        ),
    )
    op.create_index(
        "ix_member_content_likes_profile_removed",
        "member_content_likes",
        ["profile_id", "removed_at"],
    )
    op.create_table(
        "member_comments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("comment_key", sa.String(length=600), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=False),
        sa.Column("comment_html", sa.Text(), nullable=True),
        sa.Column("commented_date", sa.Date(), nullable=True),
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("profile_id", "comment_key", name="unique_member_comment"),
    )
    op.create_index(
        "ix_member_comments_profile_removed",
        "member_comments",
        ["profile_id", "removed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_member_comments_profile_removed", table_name="member_comments")
    op.drop_table("member_comments")
    op.drop_index("ix_member_content_likes_profile_removed", table_name="member_content_likes")
    op.drop_table("member_content_likes")
    op.drop_column("profiles", "pronoun")
