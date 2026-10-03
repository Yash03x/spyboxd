"""Opt-in, account-private MAL sync state; snapshots remain immutable."""
from alembic import op
import sqlalchemy as sa

revision = "20261003_0023"
down_revision = "20261003_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_anime_syncs",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("next_sync_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(255)),
    )
    op.create_index("ix_personal_anime_sync_due", "personal_anime_syncs", ["enabled", "next_sync_at"])


def downgrade():
    op.drop_table("personal_anime_syncs")
