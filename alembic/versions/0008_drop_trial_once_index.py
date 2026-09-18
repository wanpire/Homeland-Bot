"""drop the lifetime one-trial-per-telegram_id unique index

The DB-level constraint prevented the application from ever offering an
admin-toggleable "allow repeat trials" setting - a second is_trial=true
row would always be rejected at the database regardless of app-level
config. AloBot (the sibling project) hit and solved the exact same
problem for its own trial_limit_enabled toggle by dropping its
equivalent index (migration 26771c9cb9c9); this mirrors that fix.
Enforcement moves entirely to has_used_trial(), which now consults the
trial_limit_enabled app_config flag.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_vpn_users_trial_once", table_name="vpn_users")


def downgrade() -> None:
    op.create_index(
        "ix_vpn_users_trial_once", "vpn_users", ["telegram_id"],
        unique=True, postgresql_where=sa.text("is_trial = true"),
    )
