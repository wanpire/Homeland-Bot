"""vpn_users table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vpn_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("ibsng_username", sa.String(64), nullable=False),
        sa.Column("ibsng_group", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=True),
        sa.Column("data_cap_mb", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("low_quota_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vpn_users_telegram_id", "vpn_users", ["telegram_id"])
    op.create_index("ix_vpn_users_ibsng_username", "vpn_users", ["ibsng_username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_vpn_users_ibsng_username", table_name="vpn_users")
    op.drop_index("ix_vpn_users_telegram_id", table_name="vpn_users")
    op.drop_table("vpn_users")
