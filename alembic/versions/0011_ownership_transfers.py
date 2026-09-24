"""ownership_transfers: consent-based My Services account transfers

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ownership_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vpn_user_id", sa.Integer(), sa.ForeignKey("vpn_users.id"), nullable=False),
        sa.Column("from_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("to_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("offer_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ownership_transfers_vpn_user_id", "ownership_transfers", ["vpn_user_id"])


def downgrade() -> None:
    op.drop_index("ix_ownership_transfers_vpn_user_id", table_name="ownership_transfers")
    op.drop_table("ownership_transfers")
