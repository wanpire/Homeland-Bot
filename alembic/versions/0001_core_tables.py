"""core tables: bot_users, admin_users, app_config

Revision ID: 0001
Revises:
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(32), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_bot_users_telegram_id", "bot_users", ["telegram_id"], unique=True)

    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_users_telegram_id", "admin_users", ["telegram_id"], unique=True)

    op.create_table(
        "app_config",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(4096), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_config")
    op.drop_index("ix_admin_users_telegram_id", table_name="admin_users")
    op.drop_table("admin_users")
    op.drop_index("ix_bot_users_telegram_id", table_name="bot_users")
    op.drop_table("bot_users")
