"""correct catalog to the real IBSng groups, add Plan.category

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15

The 4 plans/groups seeded by 0002 were placeholders from initial
development ("HL-2W" etc.) - not real IBSng group names. This revision
replaces them with the 7 real groups on the shared IBSng instance
(spec §4, confirmed 2026-09-15), adds the `category` field the real
product needs (scroll/stream/trial), and removes the placeholder rows.
Per the same frozen-migration discipline as 0002: these literals are
private to this file, not imported from or shared with app code.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_OLD_GROUP_NAMES: tuple[str, ...] = ("HL-2W", "HL-1M", "HL-2M", "HL-3M")

# (name, duration_days, data_cap_mb, price_usd, group_name, sort_order)
_OLD_PLANS: tuple[tuple[str, int, int, str, str, int], ...] = (
    ("2 Weeks", 14, 2048, "2.50", "HL-2W", 0),
    ("1 Month", 30, 5120, "5.00", "HL-1M", 1),
    ("2 Months", 60, 10240, "10.00", "HL-2M", 2),
    ("3 Months", 90, 102400, "30.00", "HL-3M", 3),
)

_NEW_GROUP_NAMES: tuple[str, ...] = (
    "Trial-Iran",
    "2W-1U-Iran-5G",
    "1M-1U-Iran-10G",
    "2M-1U-Iran-20G",
    "1M-1U-Iran-30G",
    "2M-1U-Iran-60G",
    "3M-1U-Iran-100G",
)

# (name, category, duration_days, data_cap_mb, price_usd, group_name, sort_order)
_NEW_PLANS: tuple[tuple[str, str, int, int, str, str, int], ...] = (
    ("Trial", "trial", 1, 1024, "0.00", "Trial-Iran", 0),
    ("2 Weeks", "scroll", 14, 5120, "3.00", "2W-1U-Iran-5G", 1),
    ("1 Month", "scroll", 30, 10240, "5.00", "1M-1U-Iran-10G", 2),
    ("2 Months", "scroll", 60, 20480, "9.00", "2M-1U-Iran-20G", 3),
    ("1 Month", "stream", 30, 30720, "12.00", "1M-1U-Iran-30G", 4),
    ("2 Months", "stream", 60, 61440, "20.00", "2M-1U-Iran-60G", 5),
    ("3 Months", "stream", 90, 102400, "29.00", "3M-1U-Iran-100G", 6),
)


def upgrade() -> None:
    op.add_column("plans", sa.Column("category", sa.String(16), nullable=True))
    op.create_index("ix_plans_category", "plans", ["category"])

    plans_table = sa.table(
        "plans",
        sa.column("name", sa.String),
        sa.column("group_name", sa.String),
    )
    groups_table = sa.table("groups", sa.column("name", sa.String))

    # Delete plans before groups - group_name FK requires it.
    op.execute(plans_table.delete().where(plans_table.c.group_name.in_(_OLD_GROUP_NAMES)))
    op.execute(groups_table.delete().where(groups_table.c.name.in_(_OLD_GROUP_NAMES)))

    op.bulk_insert(groups_table, [{"name": name} for name in _NEW_GROUP_NAMES])
    op.bulk_insert(
        sa.table(
            "plans",
            sa.column("name", sa.String),
            sa.column("category", sa.String),
            sa.column("duration_days", sa.Integer),
            sa.column("data_cap_mb", sa.Integer),
            sa.column("price_usd", sa.Numeric),
            sa.column("group_name", sa.String),
            sa.column("sort_order", sa.Integer),
        ),
        [
            {
                "name": name,
                "category": category,
                "duration_days": duration_days,
                "data_cap_mb": data_cap_mb,
                "price_usd": price_usd,
                "group_name": group_name,
                "sort_order": sort_order,
            }
            for name, category, duration_days, data_cap_mb, price_usd, group_name, sort_order in _NEW_PLANS
        ],
    )

    op.alter_column("plans", "category", nullable=False)


def downgrade() -> None:
    plans_table = sa.table(
        "plans",
        sa.column("name", sa.String),
        sa.column("group_name", sa.String),
    )
    groups_table = sa.table("groups", sa.column("name", sa.String))

    op.execute(plans_table.delete().where(plans_table.c.group_name.in_(_NEW_GROUP_NAMES)))
    op.execute(groups_table.delete().where(groups_table.c.name.in_(_NEW_GROUP_NAMES)))

    # Drop `category` before inserting the old (category-less) rows below -
    # it's still NOT NULL at this point, so inserting first would violate
    # that constraint on every row.
    op.drop_index("ix_plans_category", table_name="plans")
    op.drop_column("plans", "category")

    op.bulk_insert(groups_table, [{"name": name} for name in _OLD_GROUP_NAMES])
    op.bulk_insert(
        sa.table(
            "plans",
            sa.column("name", sa.String),
            sa.column("duration_days", sa.Integer),
            sa.column("data_cap_mb", sa.Integer),
            sa.column("price_usd", sa.Numeric),
            sa.column("group_name", sa.String),
            sa.column("sort_order", sa.Integer),
        ),
        [
            {
                "name": name,
                "duration_days": duration_days,
                "data_cap_mb": data_cap_mb,
                "price_usd": price_usd,
                "group_name": group_name,
                "sort_order": sort_order,
            }
            for name, duration_days, data_cap_mb, price_usd, group_name, sort_order in _OLD_PLANS
        ],
    )
