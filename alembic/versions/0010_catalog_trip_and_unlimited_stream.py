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

The group insert is idempotent and every plan UPDATE is self-verifying
against the row's expected group_name - see the comments in upgrade().

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
_TRIP_PLAN_GROUP = "2W-1U-Iran-5G"

# (plan id, the group_name that id is expected to carry). Each pair is
# updated on its own statement rather than one combined IN (...) so that
# production drift on a single row (a manual fix, a restored dump) is an
# isolated no-op on exactly that row, instead of being masked by the two
# siblings still matching - and, crucially, so a re-used id that now
# points at some unrelated group is never deactivated by mistake.
_OLD_STREAM_PLANS: tuple[tuple[int, str], ...] = (
    (9, "1M-1U-Iran-30G"),
    (10, "2M-1U-Iran-60G"),
    (11, "3M-1U-Iran-100G"),
)
_OLD_STREAM_PLAN_IDS = tuple(plan_id for plan_id, _group in _OLD_STREAM_PLANS)

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

    # groups.name carries a unique index (ix_groups_name), and these 4
    # group names already exist on the live IBSng instance - so the bot's
    # own "🔄 Sync IBSng Groups" admin action (app/services/groups.py's
    # sync_groups) may already have upserted any or all of them before
    # this migration ever runs. An unconditional bulk_insert would then
    # hit a duplicate-key violation and abort the whole `alembic upgrade
    # head` deploy, so insert only the names that aren't there yet.
    existing_names = {
        row[0]
        for row in op.get_bind().execute(
            sa.text("SELECT name FROM groups WHERE name = ANY(:names)"),
            {"names": list(_NEW_GROUP_NAMES)},
        )
    }
    missing_groups = [{"name": name} for name in _NEW_GROUP_NAMES if name not in existing_names]
    if missing_groups:
        op.bulk_insert(groups_table, missing_groups)

    plans_table = sa.table(
        "plans",
        sa.column("id", sa.Integer),
        sa.column("category", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("group_name", sa.String),
    )

    # Every UPDATE below is self-verifying: it pins the expected
    # group_name alongside the id, so if production data has drifted
    # since the spec's 2026-09-18 verification the statement is a silent
    # no-op on the drifted row rather than recategorizing/deactivating
    # some unrelated plan that happens to now hold that id.
    op.execute(
        plans_table.update()
        .where(plans_table.c.id == _TRIP_PLAN_ID, plans_table.c.group_name == _TRIP_PLAN_GROUP)
        .values(category="trip")
    )
    for plan_id, expected_group in _OLD_STREAM_PLANS:
        op.execute(
            plans_table.update()
            .where(plans_table.c.id == plan_id, plans_table.c.group_name == expected_group)
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
    #
    # The group delete is deliberately unconditional even though
    # upgrade()'s insert is now idempotent (a row may pre-exist because
    # sync_groups created it, not because this migration did, so this
    # migration cannot claim sole ownership). That asymmetry is safe and
    # intentional: dropping a group row here is fully recoverable - the
    # groups are still live on IBSng, so the next "🔄 Sync IBSng Groups"
    # tap re-creates any of them - whereas leaving them behind would
    # break the downgrade-returns-to-the-original-state contract the
    # migration test asserts. Nothing else about downgrade needs the
    # upgrade path's self-verifying predicates: re-activating a row this
    # migration never deactivated is a far lower-risk failure mode than
    # the upgrade's mis-deactivation risk, so the plain id list stays.
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
