"""payments and payment_status_events tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("vpn_user_id", sa.Integer(), sa.ForeignKey("vpn_users.id"), nullable=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column(
            "discount_code_id", sa.Integer(), sa.ForeignKey("discount_codes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("group_name", sa.String(64), nullable=False),
        sa.Column("data_cap_mb", sa.Integer(), nullable=False),
        sa.Column("ibsng_username", sa.String(64), nullable=True),
        sa.Column("ibsng_password", sa.String(128), nullable=True),
        sa.Column("amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("original_amount_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("paid_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("provider", sa.String(16), nullable=False, server_default="nowpayments"),
        sa.Column("provider_payment_id", sa.String(64), nullable=True),
        sa.Column("invoice_url", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_payments_telegram_id", "payments", ["telegram_id"])
    op.create_index("ix_payments_provider_payment_id", "payments", ["provider_payment_id"], unique=True)

    op.create_table(
        "payment_status_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("raw_status", sa.String(32), nullable=False),
        sa.Column("paid_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_payment_status_events_payment_id", "payment_status_events", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_status_events_payment_id", table_name="payment_status_events")
    op.drop_table("payment_status_events")
    op.drop_index("ix_payments_provider_payment_id", table_name="payments")
    op.drop_index("ix_payments_telegram_id", table_name="payments")
    op.drop_table("payments")
