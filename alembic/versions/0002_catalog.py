"""catalog: groups, plans, seeded with Homeland's 4 fixed plans

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa

from app.db.seed_data import SEED_GROUP_NAMES, SEED_PLANS

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_groups_name", "groups", ["name"], unique=True)

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("data_cap_mb", sa.Integer(), nullable=False),
        sa.Column("price_usd", sa.Numeric(6, 2), nullable=False),
        sa.Column("group_name", sa.String(64), sa.ForeignKey("groups.name"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_plans_group_name", "plans", ["group_name"])

    groups_table = sa.table("groups", sa.column("name", sa.String))
    plans_table = sa.table(
        "plans",
        sa.column("name", sa.String),
        sa.column("duration_days", sa.Integer),
        sa.column("data_cap_mb", sa.Integer),
        sa.column("price_usd", sa.Numeric),
        sa.column("group_name", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(groups_table, [{"name": group_name} for group_name in SEED_GROUP_NAMES])
    op.bulk_insert(
        plans_table,
        [
            {
                "name": name,
                "duration_days": duration_days,
                "data_cap_mb": data_cap_mb,
                "price_usd": price_usd,
                "group_name": group_name,
                "sort_order": sort_order,
            }
            for name, duration_days, data_cap_mb, price_usd, group_name, sort_order in SEED_PLANS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_plans_group_name", table_name="plans")
    op.drop_table("plans")
    op.drop_index("ix_groups_name", table_name="groups")
    op.drop_table("groups")
