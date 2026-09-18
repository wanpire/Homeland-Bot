"""catalog restructure: trip category, unlimited-data Stream, Scroll 3M tier

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-18

Homeland's real IBSng groups changed on the shared instance: the old
capped-Stream groups (1M-1U-Iran-30G, 2M-1U-Iran-60G, 3M-1U-Iran-100G) no
longer exist there, replaced by three -Unlimited groups; a new Scroll
3-month group (3M-1U-Iran-30G) was added; 2W-1U-Iran-5G becomes its own
"trip" category instead of a Scroll tier. Confirmed against both the live
IBSng group list and production plans/payments data on 2026-09-18 (see
docs/superpowers/specs/2026-09-18-catalog-restructure-and-manage-plans-design.md
section 1).

Plans 6 ("2 Weeks"), 9 ("1 Month" stream), and 11 ("3 Months" stream) are
referenced by real Payment rows in production - this migration never
deletes a plans or groups row. Plan 6 is recategorized in place (its
plan_id, group, and price are unchanged). Plans 9/10/11 are deactivated,
not deleted, since their IBSng groups are gone and they must vanish from
Buy/Renew regardless of the separate Manage Plans admin feature. Four new
plan rows are inserted for the new IBSng groups, all is_active=False with
a $0.00 placeholder price - the admin sets real prices and activates each
one individually through Manage Plans after this migration runs, so
nothing at a wrong or placeholder price is ever customer-visible.

Per the same frozen-migration discipline as 0002/0004: these literals are
private to this file, never imported from or shared with app code.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_TRIP_PLAN_ID = 6
_OLD_STREAM_PLAN_IDS = (9, 10, 11)

_NEW_GROUP_NAMES: tuple[str, ...] = (
    "3M-1U-Iran-30G",
    "1M-1U-Iran-Unlimited",
    "2M-1U-Iran-Unlimited",
    "3M-1U-Iran-Unlimited",
)

# (name, category, duration_days, data_cap_mb, price_usd, group_name, sort_order)
# data_cap_mb=0 is the "Unlimited" sentinel (app/services/catalog.py's
# format_data_cap). price_usd is a $0.00 placeholder - every row here is
# inserted is_active=False; the admin sets the real price via Manage
# Plans before activating it.
_NEW_PLANS: tuple[tuple[str, str, int, int, str, str, int], ...] = (
    ("3 Months", "scroll", 90, 30720, "0.00", "3M-1U-Iran-30G", 7),
    ("1 Month", "stream", 30, 0, "0.00", "1M-1U-Iran-Unlimited", 8),
    ("2 Months", "stream", 60, 0, "0.00", "2M-1U-Iran-Unlimited", 9),
    ("3 Months", "stream", 90, 0, "0.00", "3M-1U-Iran-Unlimited", 10),
)


def upgrade() -> None:
    groups_table = sa.table("groups", sa.column("name", sa.String))
    op.bulk_insert(groups_table, [{"name": name} for name in _NEW_GROUP_NAMES])

    plans_table = sa.table(
        "plans",
        sa.column("id", sa.Integer),
        sa.column("category", sa.String),
        sa.column("is_active", sa.Boolean),
    )

    op.execute(
        plans_table.update()
        .where(plans_table.c.id == _TRIP_PLAN_ID)
        .values(category="trip")
    )
    op.execute(
        plans_table.update()
        .where(plans_table.c.id.in_(_OLD_STREAM_PLAN_IDS))
        .values(is_active=False)
    )

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
            sa.column("is_active", sa.Boolean),
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
                "is_active": False,
            }
            for name, category, duration_days, data_cap_mb, price_usd, group_name, sort_order in _NEW_PLANS
        ],
    )


def downgrade() -> None:
    plans_table = sa.table(
        "plans",
        sa.column("id", sa.Integer),
        sa.column("category", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("group_name", sa.String),
    )
    groups_table = sa.table("groups", sa.column("name", sa.String))

    new_group_names = list(_NEW_GROUP_NAMES)

    # Delete the 4 new plan rows before their groups - group_name FK
    # requires it.
    op.execute(plans_table.delete().where(plans_table.c.group_name.in_(new_group_names)))
    op.execute(groups_table.delete().where(groups_table.c.name.in_(new_group_names)))

    op.execute(
        plans_table.update()
        .where(plans_table.c.id.in_(_OLD_STREAM_PLAN_IDS))
        .values(is_active=True)
    )
    op.execute(
        plans_table.update()
        .where(plans_table.c.id == _TRIP_PLAN_ID)
        .values(category="scroll")
    )
