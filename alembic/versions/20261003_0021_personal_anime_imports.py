"""Private, owner-scoped MAL export snapshots (additive).

Revision ID: 20261003_0021
Revises: 20260810_0020
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261003_0021"
down_revision = "20260810_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_anime_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mal_username", sa.String(64), nullable=False),
        sa.Column("mal_user_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "source_hash", name="uq_personal_anime_import_source"),
    )
    op.create_index("ix_personal_anime_import_owner", "personal_anime_imports", ["user_id", "id"])


def downgrade():
    op.drop_index("ix_personal_anime_import_owner", table_name="personal_anime_imports")
    op.drop_table("personal_anime_imports")
