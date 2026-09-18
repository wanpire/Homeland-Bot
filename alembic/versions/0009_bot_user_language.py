"""add BotUser.language for bilingual customer-facing flows

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_users", sa.Column("language", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_users", "language")
