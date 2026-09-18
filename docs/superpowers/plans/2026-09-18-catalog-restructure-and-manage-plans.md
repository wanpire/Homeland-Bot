# Catalog Restructure + Manage Plans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure Homeland's plan catalog to match the real, already-changed IBSng groups (new `trip` category, unlimited-data Stream tiers, a new Scroll 3-month tier) and add a "Manage Plans" admin screen so price and active-status can be edited from the bot instead of via migration.

**Architecture:** A single new Alembic migration updates/inserts `plans`/`groups` rows without ever deleting a row a `Payment` or `VPNUser` references. `app/services/catalog.py` gains an Unlimited-aware `format_data_cap` and a `trip` category. A new admin screen, wired into the existing `admin_settings` router (already gated `IsFullAdmin` at router level), edits `Plan.price_usd`/`Plan.is_active` through the already-existing `update_plan` service function.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, Alembic, PostgreSQL, pytest+pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-18-catalog-restructure-and-manage-plans-design.md`

## Global Constraints

- Never delete a `Plan` or `Group` row that any `Payment` or `VPNUser` row references (plans 6, 9, 11 all carry real payment history — verified against production on 2026-09-18). Retiring a plan means `is_active=False`, never a delete.
- The 4 newly inserted plan rows ship `is_active=False`, `price_usd='0.00'` — an admin makes them customer-visible only via Manage Plans, after setting a real price.
- Manage Plans edits **only** `price_usd` and `is_active` on existing rows. It never creates or deletes a `Plan` row and never edits `group_name` in this pass.
- Customer-facing strings go through `app/i18n/texts.py`'s `t()`, both languages. Manage Plans is entirely admin-facing — plain English strings only, never `t()`, matching every other screen in `app/bot/handlers/admin_settings.py`.
- `format_data_cap`'s new `lang` parameter is required (no default) — every call site touched by this plan already needs updating.
- `data_cap_mb == 0` is the sentinel for "Unlimited" — the column itself stays a required, non-nullable `Integer`.

---

## File Structure

- **Modify** `alembic/versions/0009_bot_user_language.py` → read only, to confirm the new migration's `down_revision`.
- **Create** `alembic/versions/0010_catalog_trip_and_unlimited_stream.py` — the catalog restructure migration (Task 1).
- **Modify** `app/services/catalog.py` — `format_data_cap` gains `lang`, `CATEGORIES` gains `"trip"`, `_CATEGORY_KEYS` gains `"trip"` (Task 2).
- **Modify** `app/i18n/texts.py` — new keys `data_cap_unlimited`, `category_trip` (Task 2).
- **Modify** `app/bot/keyboards/buy.py`, `app/bot/handlers/buy.py` — Trip button, `format_data_cap` call sites (Task 2).
- **Modify** `app/bot/keyboards/renew.py`, `app/bot/handlers/renew.py` — Trip button, `format_data_cap` call sites (Task 2).
- **Create** `app/bot/keyboards/manage_plans.py` — list/detail/edit keyboards for the new admin feature (Task 3).
- **Modify** `app/bot/keyboards/admin.py` — "💰 Manage Plans" button in `admin_settings_menu()` (Task 3).
- **Modify** `app/bot/states/admin_settings.py` — new `EditPlanPriceStates` (Task 3).
- **Modify** `app/bot/handlers/admin_settings.py` — new handlers for the list/detail/price-edit/toggle screens (Task 3).
- **Test:** `tests/functional/test_catalog_migration.py` (new, Task 1), `tests/functional/test_catalog.py` (extend, Task 2), `tests/functional/test_buy_flow.py`/`test_renew_flow.py` (extend, Task 2), `tests/functional/test_admin_manage_plans.py` (new, Task 3).

---

## Task 1: Catalog Restructure Migration

**Files:**
- Create: `alembic/versions/0010_catalog_trip_and_unlimited_stream.py`
- Test: `tests/functional/test_catalog_migration.py`

**Interfaces:**
- Consumes: nothing from later tasks.
- Produces: the post-migration `plans`/`groups` state every later task's tests assume — specifically, plan id 6 has `category='trip'`, plans 9/10/11 have `is_active=False`, and 4 new inactive plan rows exist for groups `3M-1U-Iran-30G` (scroll), `1M-1U-Iran-Unlimited`/`2M-1U-Iran-Unlimited`/`3M-1U-Iran-Unlimited` (stream), each with `data_cap_mb` per the table below and `price_usd='0.00'`.

- [ ] **Step 1: Write the failing test**

Create `tests/functional/test_catalog_migration.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models.group import Group
from app.db.models.plan import Plan
from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_migration_0010_state() -> None:
    """No special fixture is needed here: conftest.py's `_migrate_test_database`
    (session-scoped, autouse) already runs `alembic upgrade head` before any
    test executes, and `_clean_database` (autouse, runs before every test)
    re-seeds `groups`/`plans` from whatever `seeded_catalog` read back right
    after that migration run - so by the time this test body runs, the DB
    already reflects migration 0010's final state. This test just asserts
    that state; it does not run alembic itself."""
    async with async_session_maker() as session:
        plans_by_id = {
            p.id: p for p in (await session.execute(select(Plan))).scalars().all()
        }

        # Plan 6 recategorized in place - same id, same group, same price.
        trip_plan = plans_by_id[6]
        assert trip_plan.category == "trip"
        assert trip_plan.group_name == "2W-1U-Iran-5G"
        assert trip_plan.price_usd == Decimal("3.00")
        assert trip_plan.is_active is True

        # Old capped-Stream plans deactivated, never deleted.
        for old_stream_id in (9, 10, 11):
            assert plans_by_id[old_stream_id].is_active is False

        # 4 new rows: inactive, $0.00, correct group/category/cap.
        new_rows = {
            p.group_name: p
            for p in plans_by_id.values()
            if p.group_name
            in ("3M-1U-Iran-30G", "1M-1U-Iran-Unlimited", "2M-1U-Iran-Unlimited", "3M-1U-Iran-Unlimited")
        }
        assert len(new_rows) == 4
        for plan in new_rows.values():
            assert plan.is_active is False
            assert plan.price_usd == Decimal("0.00")

        assert new_rows["3M-1U-Iran-30G"].category == "scroll"
        assert new_rows["3M-1U-Iran-30G"].data_cap_mb == 30720
        assert new_rows["3M-1U-Iran-30G"].duration_days == 90

        for group_name, duration_days in (
            ("1M-1U-Iran-Unlimited", 30),
            ("2M-1U-Iran-Unlimited", 60),
            ("3M-1U-Iran-Unlimited", 90),
        ):
            plan = new_rows[group_name]
            assert plan.category == "stream"
            assert plan.data_cap_mb == 0
            assert plan.duration_days == duration_days

        # Nothing was deleted - row count only grew (7 original + 4 new = 11).
        assert len(plans_by_id) == 11

        group_names = {g.name for g in (await session.execute(select(Group))).scalars().all()}
        for name in ("3M-1U-Iran-30G", "1M-1U-Iran-Unlimited", "2M-1U-Iran-Unlimited", "3M-1U-Iran-Unlimited"):
            assert name in group_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/functional/test_catalog_migration.py -v`
Expected: FAIL — plan 6's category is still `"scroll"` (the migration doesn't exist yet), or a `KeyError` on the new group names.

- [ ] **Step 3: Write the migration**

Create `alembic/versions/0010_catalog_trip_and_unlimited_stream.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/functional/test_catalog_migration.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing suite to confirm zero regressions**

Run: `pytest tests/ -v`
Expected: every pre-existing test still passes — this migration only
updates/inserts rows, it doesn't touch schema, so no other test's
assumptions about table shape should be affected. If any existing test
hardcodes the total plan count or iterates `list_plans()` without a
category filter and asserts an exact count, update that assertion to
account for the 4 new (inactive, so usually filtered out by
`active_only=True`) rows — inspect any failure here rather than assuming
none will occur.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/0010_catalog_trip_and_unlimited_stream.py tests/functional/test_catalog_migration.py
git commit -m "feat: restructure catalog for trip category and unlimited-data Stream tiers"
```

---

## Task 2: i18n, Catalog Service, and Category UI

**Files:**
- Modify: `app/i18n/texts.py`
- Modify: `app/services/catalog.py`
- Modify: `app/bot/keyboards/buy.py`
- Modify: `app/bot/handlers/buy.py`
- Modify: `app/bot/keyboards/renew.py`
- Modify: `app/bot/handlers/renew.py`
- Test: `tests/functional/test_catalog.py`, `tests/functional/test_buy_flow.py`, `tests/functional/test_renew_flow.py`

**Interfaces:**
- Consumes: Task 1's migrated catalog state (the `trip` category plan, the inactive Unlimited-Stream/Scroll-3M plans an admin will later activate).
- Produces: `format_data_cap(data_cap_mb: int, lang: str) -> str` (breaking signature change — every call site in this codebase is updated in this task); `CATEGORIES = ("scroll", "stream", "trip", "trial")`; new i18n keys `data_cap_unlimited`, `category_trip`, both consumed by Task 3's admin screens (which always pass `lang="en"`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/functional/test_catalog.py` (create the file if it doesn't already exist — check first; if it exists, add these test functions to it):

```python
def test_format_data_cap_unlimited_sentinel() -> None:
    from app.services.catalog import format_data_cap

    assert format_data_cap(0, "en") == "Unlimited"
    assert format_data_cap(0, "fa") == "نامحدود"


def test_format_data_cap_gb_and_mb_still_work_with_lang() -> None:
    from app.services.catalog import format_data_cap

    assert format_data_cap(10240, "en") == "10 GB"
    assert format_data_cap(500, "en") == "500 MB"
    assert format_data_cap(10240, "fa") == "10 GB"


def test_categories_includes_trip() -> None:
    from app.services.catalog import CATEGORIES

    assert "trip" in CATEGORIES


def test_category_display_name_trip() -> None:
    from app.services.catalog import category_display_name

    assert category_display_name("trip", "en") == "🧳 Trip"
    assert category_display_name("trip", "fa") == "🧳 سفر کوتاه"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_catalog.py -v -k "unlimited or trip or format_data_cap"`
Expected: FAIL — `format_data_cap()` doesn't accept a `lang` argument yet, `"trip"` isn't in `CATEGORIES`.

- [ ] **Step 3: Add the new i18n keys**

In `app/i18n/texts.py`, in the `"en"` dict, immediately after the existing `"category_trial": "Trial",` line (in the "buy.py / buy keyboard" section):

```python
        "category_trip": "🧳 Trip",
```

In the same dict, immediately after the "plan display names (catalog.py)" section's existing 5 keys (after `"plan_name_3months": "3 Months",`), add a new subsection:

```python

        # --- data cap display (catalog.py) ---
        "data_cap_unlimited": "Unlimited",
```

In the `"fa"` dict, immediately after the existing `"category_trial": "تست رایگان",` line:

```python
        "category_trip": "🧳 سفر کوتاه",
```

And immediately after the fa `"plan_name_3months": "۳ ماه",` line:

```python
        "data_cap_unlimited": "نامحدود",
```

- [ ] **Step 4: Update `format_data_cap` and the category maps**

In `app/services/catalog.py`, replace:

```python
CATEGORIES = ("scroll", "stream", "trial")
```

with:

```python
CATEGORIES = ("scroll", "stream", "trip", "trial")
```

Replace:

```python
def format_data_cap(data_cap_mb: int) -> str:
    if data_cap_mb % 1024 == 0:
        return f"{data_cap_mb // 1024} GB"
    return f"{data_cap_mb} MB"
```

with:

```python
def format_data_cap(data_cap_mb: int, lang: str) -> str:
    if data_cap_mb == 0:
        return t("data_cap_unlimited", lang)
    if data_cap_mb % 1024 == 0:
        return f"{data_cap_mb // 1024} GB"
    return f"{data_cap_mb} MB"
```

Replace:

```python
_CATEGORY_KEYS = {"scroll": "category_scroll", "stream": "category_stream", "trial": "category_trial"}
```

with:

```python
_CATEGORY_KEYS = {
    "scroll": "category_scroll",
    "stream": "category_stream",
    "trip": "category_trip",
    "trial": "category_trial",
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/functional/test_catalog.py -v -k "unlimited or trip or format_data_cap"`
Expected: PASS

- [ ] **Step 6: Update every `format_data_cap` call site**

In `app/bot/keyboards/buy.py`, in `buy_plan_keyboard`, replace:

```python
            text=f"{plan_display_name(plan, lang)} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb)})",
```

with:

```python
            text=f"{plan_display_name(plan, lang)} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb, lang)})",
```

And add a third category button in `buy_category_keyboard`. Replace:

```python
def buy_category_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=category_display_name("scroll", lang), callback_data="buy:category:scroll")
    builder.button(text=category_display_name("stream", lang), callback_data="buy:category:stream")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()
```

with:

```python
def buy_category_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=category_display_name("scroll", lang), callback_data="buy:category:scroll")
    builder.button(text=category_display_name("stream", lang), callback_data="buy:category:stream")
    builder.button(text=category_display_name("trip", lang), callback_data="buy:category:trip")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1, 1)
    return builder.as_markup()
```

In `app/bot/handlers/buy.py`, in `_price_summary_text`, replace:

```python
        t("price_data", lang, cap=format_data_cap(plan.data_cap_mb)),
```

with:

```python
        t("price_data", lang, cap=format_data_cap(plan.data_cap_mb, lang)),
```

No change is needed to `_BUY_CATEGORIES` or `buy_category_cb`'s validation — both already derive from `CATEGORIES` (`_BUY_CATEGORIES = tuple(category for category in CATEGORIES if category != "trial")`), so `"trip"` is automatically buyable the moment it's added to `CATEGORIES` in Step 4.

In `app/bot/keyboards/renew.py`, add the same third button. Replace:

```python
def renew_category_keyboard(vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=category_display_name("scroll", lang), callback_data=f"renew:category:{vpn_user_id}:scroll")
    builder.button(text=category_display_name("stream", lang), callback_data=f"renew:category:{vpn_user_id}:stream")
    builder.button(text=t("back_to_list_button", lang), callback_data="menu:renew")
    builder.adjust(2, 1)
    return builder.as_markup()
```

with:

```python
def renew_category_keyboard(vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=category_display_name("scroll", lang), callback_data=f"renew:category:{vpn_user_id}:scroll")
    builder.button(text=category_display_name("stream", lang), callback_data=f"renew:category:{vpn_user_id}:stream")
    builder.button(text=category_display_name("trip", lang), callback_data=f"renew:category:{vpn_user_id}:trip")
    builder.button(text=t("back_to_list_button", lang), callback_data="menu:renew")
    builder.adjust(2, 1, 1)
    return builder.as_markup()
```

In `app/bot/handlers/renew.py`, in `_renew_summary_text`, replace:

```python
        t("price_data", lang, cap=format_data_cap(plan.data_cap_mb)),
```

with:

```python
        t("price_data", lang, cap=format_data_cap(plan.data_cap_mb, lang)),
```

Same as `buy.py`: `_RENEW_CATEGORIES` and `renew_category_cb`'s validation already derive from `CATEGORIES`, so no further change is needed there.

- [ ] **Step 7: Write and run the Buy/Renew Trip-flow tests**

Add to `tests/functional/test_buy_flow.py`:

```python
@pytest.mark.asyncio
async def test_trip_category_button_present_and_routes(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_USER_ID, "menu:buy"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    trip_buttons = [b for row in keyboard for b in row if b["callback_data"] == "buy:category:trip"]
    assert len(trip_buttons) == 1

    await dispatcher.feed_update(bot, make_callback_update(FAKE_USER_ID, "buy:category:trip"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    plan_buttons = [b for row in keyboard for b in row if b["callback_data"].startswith("buy:plan:")]
    assert len(plan_buttons) == 1
    assert "2 Weeks" in plan_buttons[0]["text"]
```

(Use this file's existing imports for `Any`, `pytest`, `make_callback_update`, `FAKE_USER_ID`, `FakeBotSession` — do not re-import if already present; match whatever names the existing tests in this file already use for the fake regular-user id.)

Add to `tests/functional/test_renew_flow.py` (only if a renewable service already exists in that file's fixtures/setup for the test user — if not, follow that file's existing pattern for creating one before asserting on category buttons):

```python
@pytest.mark.asyncio
async def test_renew_trip_category_button_present(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    # Reuse this file's existing setup for a renewable VPNUser owned by
    # the fake test user before this callback - see the file's other
    # tests for the exact fixture/helper it uses.
    ...
```

Run: `pytest tests/functional/test_buy_flow.py tests/functional/test_renew_flow.py -v`
Expected: PASS. If `test_renew_flow.py`'s existing setup pattern differs from
what's sketched above (e.g. a fixture name, a factory helper), read that
file's other passing tests first and match its actual pattern exactly
rather than guessing — the `...` placeholder above must be replaced with
real, runnable code before this step is considered done.

- [ ] **Step 8: Run the full existing suite**

Run: `pytest tests/ -v`
Expected: all tests pass, including every pre-existing `format_data_cap`
call site now updated in Steps 6-7.

- [ ] **Step 9: Commit**

```bash
git add app/i18n/texts.py app/services/catalog.py app/bot/keyboards/buy.py app/bot/handlers/buy.py app/bot/keyboards/renew.py app/bot/handlers/renew.py tests/functional/test_catalog.py tests/functional/test_buy_flow.py tests/functional/test_renew_flow.py
git commit -m "feat: add Trip category and bilingual Unlimited data-cap display"
```

---

## Task 3: Manage Plans Admin Feature

**Files:**
- Create: `app/bot/keyboards/manage_plans.py`
- Modify: `app/bot/keyboards/admin.py`
- Modify: `app/bot/states/admin_settings.py`
- Modify: `app/bot/handlers/admin_settings.py`
- Test: `tests/functional/test_admin_manage_plans.py`

**Interfaces:**
- Consumes: `app.services.catalog.list_plans(session, category=None, active_only=False)`, `get_plan(session, plan_id)`, `update_plan(session, plan_id, price_usd=..., is_active=...)` (all already exist, unchanged); `format_price_usd(price)`, `format_data_cap(data_cap_mb, lang)` (Task 2's signature) — Manage Plans always calls `format_data_cap(..., "en")`.
- Produces: nothing consumed by later tasks (this is the plan's final task).

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_admin_manage_plans.py`:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_full_admin_cannot_open_manage_plans(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=622, level="sales"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(622, "adm:settings:plans"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("manage plans" in c[1].get("text", "").lower() for c in edited)


@pytest.mark.asyncio
async def test_manage_plans_list_shows_every_plan_grouped(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plans"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    plan_buttons = [b for row in keyboard for b in row if b["callback_data"].startswith("adm:settings:plan:") and b["callback_data"].count(":") == 3]
    # 7 original + 4 new from the Task 1 migration = 11 plan rows total.
    assert len(plan_buttons) == 11


@pytest.mark.asyncio
async def test_manage_plans_detail_view_shows_fields(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:6"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[-1][1]["text"]
    assert "2W-1U-Iran-5G" in text
    assert "$3.00" in text
    assert "trip" in text.lower()


@pytest.mark.asyncio
async def test_price_edit_happy_path(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.catalog import get_plan

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:price"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "12.50"))

    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.price_usd == Decimal("12.50")

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("$12.50" in c[1].get("text", "") for c in sent)


@pytest.mark.asyncio
async def test_price_edit_rejects_non_numeric_input(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.catalog import get_plan

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:price"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "not-a-number"))

    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.price_usd == Decimal("9.00")  # unchanged

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("valid" in c[1].get("text", "").lower() or "number" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_price_edit_rejects_price_at_or_above_1000(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.catalog import get_plan

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:price"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "1000"))

    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.price_usd == Decimal("9.00")  # unchanged


@pytest.mark.asyncio
async def test_toggle_active_hides_plan_from_buy_flow(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:toggle"))

    from app.services.catalog import get_plan
    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.is_active is False

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "menu:buy"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "buy:category:scroll"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    plan_buttons = [b for row in keyboard for b in row if b["callback_data"].startswith("buy:plan:")]
    # Plan 8 ("2 Months" scroll) is now inactive - only plan 7 ("1 Month") remains.
    assert len(plan_buttons) == 1
    assert not any(b["callback_data"] == "buy:plan:8" for b in plan_buttons)


@pytest.mark.asyncio
async def test_price_change_does_not_affect_existing_payment_amount(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.catalog import get_plan, update_plan
    from app.services.payments.service import create_crypto_payment

    async with async_session_maker() as session:
        plan = await get_plan(session, 7)
        assert plan is not None
        payment = await create_crypto_payment(
            session, telegram_id=FAKE_ADMIN_ID, purpose="purchase", plan=plan, vpn_user=None,
        )
        original_amount = payment.amount_usd
        payment_id = payment.id

    async with async_session_maker() as session:
        await update_plan(session, 7, price_usd=Decimal("999.00"))

    async with async_session_maker() as session:
        from app.db.models.payment import Payment
        refreshed = await session.get(Payment, payment_id)
        assert refreshed is not None
        assert refreshed.amount_usd == original_amount
        assert refreshed.amount_usd != Decimal("999.00")
```

(This file's `create_crypto_payment` call needs the same NOWPayments-configured-or-not handling as `test_buy_flow.py`'s own payment-creation tests — check that file's setup/mocking for `PaymentProviderNotConfiguredError`/a configured fake provider, and match it exactly so this test doesn't fail for an unrelated reason.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_admin_manage_plans.py -v`
Expected: FAIL — `adm:settings:plans` doesn't route anywhere yet (no handler registered), so no message gets edited and every assertion on `edited[-1]` raises `IndexError`.

- [ ] **Step 3: Add the FSM state**

In `app/bot/states/admin_settings.py`, add:

```python
class EditPlanPriceStates(StatesGroup):
    price = State()
```

- [ ] **Step 4: Write the keyboards**

Create `app/bot/keyboards/manage_plans.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.services.catalog import format_data_cap, format_price_usd

_CATEGORY_EMOJI = {"trial": "🎁", "scroll": "📜", "stream": "🌊", "trip": "🧳"}


def manage_plans_list_keyboard(plans_by_category: dict[str, list[Plan]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []
    for category, plans in plans_by_category.items():
        emoji = _CATEGORY_EMOJI.get(category, "")
        for plan in plans:
            status = "✅" if plan.is_active else "🚫"
            builder.button(
                text=f"{emoji} {plan.name} — {format_price_usd(plan.price_usd)} {status}",
                callback_data=f"adm:settings:plan:{plan.id}",
            )
            sizes.append(1)
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    sizes.append(1)
    builder.adjust(*sizes)
    return builder.as_markup()


def manage_plans_detail_keyboard(plan: Plan) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit Price", callback_data=f"adm:settings:plan:{plan.id}:price")
    toggle_label = "🚫 Deactivate" if plan.is_active else "✅ Activate"
    builder.button(text=toggle_label, callback_data=f"adm:settings:plan:{plan.id}:toggle")
    builder.button(text="⬅️ Back to Plans", callback_data="adm:settings:plans")
    builder.adjust(1)
    return builder.as_markup()


def manage_plans_price_edit_cancel_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data=f"adm:settings:plan:{plan_id}")
    builder.adjust(1)
    return builder.as_markup()


def plan_detail_text(plan: Plan) -> str:
    status = "✅ Active" if plan.is_active else "🚫 Inactive"
    return (
        f"💰 <b>{plan.name} ({plan.category})</b>\n\n"
        f"Duration: {plan.duration_days} days\n"
        f"Data cap: {format_data_cap(plan.data_cap_mb, 'en')}\n"
        f"Group: {plan.group_name}\n"
        f"Price: {format_price_usd(plan.price_usd)}\n"
        f"Status: {status}"
    )
```

- [ ] **Step 5: Wire the admin_settings_menu() button**

In `app/bot/keyboards/admin.py`, in `admin_settings_menu()`, replace:

```python
def admin_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="☎️ Support Contact", callback_data="adm:settings:support")
    builder.button(text="🔄 Sync IBSng Groups", callback_data="adm:settings:syncgroups")
    builder.button(text="📢 Mandatory Channel", callback_data="adm:settings:channel")
    builder.button(text="⏰ Renewal Reminders", callback_data="adm:settings:reminders")
    builder.button(text="🎁 Trial Limit", callback_data="adm:settings:trial")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
```

with:

```python
def admin_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="☎️ Support Contact", callback_data="adm:settings:support")
    builder.button(text="🔄 Sync IBSng Groups", callback_data="adm:settings:syncgroups")
    builder.button(text="📢 Mandatory Channel", callback_data="adm:settings:channel")
    builder.button(text="⏰ Renewal Reminders", callback_data="adm:settings:reminders")
    builder.button(text="🎁 Trial Limit", callback_data="adm:settings:trial")
    builder.button(text="💰 Manage Plans", callback_data="adm:settings:plans")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 6: Write the handlers**

In `app/bot/handlers/admin_settings.py`, add these imports alongside the existing ones at the top of the file:

```python
import datetime as dt
import logging
from decimal import Decimal, InvalidOperation

from app.bot.keyboards.manage_plans import (
    manage_plans_detail_keyboard,
    manage_plans_list_keyboard,
    manage_plans_price_edit_cancel_keyboard,
    plan_detail_text,
)
from app.bot.states.admin_settings import EditPlanPriceStates
from app.services.catalog import format_price_usd, get_plan, list_plans, update_plan
```

(`EditMandatoryChannelStates, EditReminderStates, EditSupportStates` are already imported from `app.bot.states.admin_settings` on one line — add `EditPlanPriceStates` to that same existing import line rather than duplicating the import.)

Add a module-level logger and the category display order, near the top of the file below the existing `_SYNC_FAILED_TEXT` constant:

```python
logger = logging.getLogger(__name__)

_MANAGE_PLANS_CATEGORY_ORDER = ("trial", "scroll", "stream", "trip")
_MAX_PLAN_PRICE = Decimal("1000")
_INVALID_PRICE_TEXT = "⚠️ Send a valid price — a positive number under $1000 (e.g. 12.50)."
```

Append these handlers at the end of the file:

```python
async def _grouped_plans(session: AsyncSession) -> dict[str, list]:
    plans = await list_plans(session, active_only=False)
    grouped: dict[str, list] = {category: [] for category in _MANAGE_PLANS_CATEGORY_ORDER}
    for plan in plans:
        grouped.setdefault(plan.category, []).append(plan)
    return grouped


@router.callback_query(F.data == "adm:settings:plans")
async def manage_plans_list_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        grouped = await _grouped_plans(session)
    if callback.message is not None:
        await callback.message.edit_text(
            "💰 <b>Manage Plans</b>\n\nTap a plan to edit its price or active status.",
            reply_markup=manage_plans_list_keyboard(grouped),
        )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^adm:settings:plan:\d+$"))
async def manage_plan_detail_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
    if plan is None:
        if callback.message is not None:
            await callback.message.edit_text("⚠️ Plan not found.", reply_markup=back_to_settings_keyboard())
        await callback.answer()
        return
    if callback.message is not None:
        await callback.message.edit_text(plan_detail_text(plan), reply_markup=manage_plans_detail_keyboard(plan))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^adm:settings:plan:\d+:price$"))
async def manage_plan_edit_price_cb(callback: CallbackQuery, state: FSMContext) -> None:
    plan_id = int(callback.data.split(":")[-2])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
    if plan is None:
        if callback.message is not None:
            await callback.message.edit_text("⚠️ Plan not found.", reply_markup=back_to_settings_keyboard())
        await callback.answer()
        return
    await state.set_state(EditPlanPriceStates.price)
    await state.update_data(plan_id=plan_id)
    if callback.message is not None:
        await callback.message.edit_text(
            f"Current price for {plan.name} ({plan.category}): {format_price_usd(plan.price_usd)}\n\n"
            "Send the new price (e.g. 12.50):",
            reply_markup=manage_plans_price_edit_cancel_keyboard(plan_id),
        )
    await callback.answer()


@router.message(EditPlanPriceStates.price)
async def manage_plan_receive_price(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plan_id = data["plan_id"]
    raw = (message.text or "").strip()

    try:
        new_price = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        await message.answer(_INVALID_PRICE_TEXT, reply_markup=manage_plans_price_edit_cancel_keyboard(plan_id))
        return
    if new_price <= 0 or new_price >= _MAX_PLAN_PRICE:
        await message.answer(_INVALID_PRICE_TEXT, reply_markup=manage_plans_price_edit_cancel_keyboard(plan_id))
        return

    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if plan is None:
            await state.clear()
            await message.answer("⚠️ Plan not found.", reply_markup=back_to_settings_keyboard())
            return
        old_price = plan.price_usd
        updated = await update_plan(session, plan_id, price_usd=new_price)

    logger.info(
        "admin_price_change",
        extra={
            "admin_telegram_id": message.from_user.id if message.from_user is not None else None,
            "plan_id": plan_id,
            "old_price": str(old_price),
            "new_price": str(new_price),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
    )

    await state.clear()
    if updated is not None:
        await message.answer(
            f"✅ Price updated to {format_price_usd(updated.price_usd)}.\n\n{plan_detail_text(updated)}",
            reply_markup=manage_plans_detail_keyboard(updated),
        )


@router.callback_query(F.data.regexp(r"^adm:settings:plan:\d+:toggle$"))
async def manage_plan_toggle_active_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    plan_id = int(callback.data.split(":")[-2])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if plan is None:
            if callback.message is not None:
                await callback.message.edit_text("⚠️ Plan not found.", reply_markup=back_to_settings_keyboard())
            await callback.answer()
            return
        updated = await update_plan(session, plan_id, is_active=not plan.is_active)

    if callback.message is not None and updated is not None:
        await callback.message.edit_text(plan_detail_text(updated), reply_markup=manage_plans_detail_keyboard(updated))
    await callback.answer()
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `pytest tests/functional/test_admin_manage_plans.py -v`
Expected: PASS. If `make_callback_update`/`make_message_update`/`FAKE_ADMIN_ID`
don't match `tests/factories.py`'s actual names, or `AdminUser`'s actual
field names differ from what Step 1's tests assume, fix the test file to
match — the existing `test_admin_settings.py` read during planning is the
source of truth for these names, not this plan's transcription of it.

- [ ] **Step 8: Run the full existing suite**

Run: `pytest tests/ -v`
Expected: every test passes — Task 3 adds new routes under
`adm:settings:plan*`, which don't overlap any existing callback pattern
(`adm:settings:support`, `:syncgroups`, `:channel*`, `:reminders*`,
`:trial*` are all distinct literal/prefix matches).

- [ ] **Step 9: Commit**

```bash
git add app/bot/keyboards/manage_plans.py app/bot/keyboards/admin.py app/bot/states/admin_settings.py app/bot/handlers/admin_settings.py tests/functional/test_admin_manage_plans.py
git commit -m "feat: add Manage Plans admin screen for editing price and active status"
```

---

## Self-Review

**1. Spec coverage:**
- Spec §2.1 (Trip recategorization) → Task 1, Step 3 (`_TRIP_PLAN_ID` update).
- Spec §2.2 (old-Stream deactivation) → Task 1, Step 3 (`_OLD_STREAM_PLAN_IDS` update).
- Spec §2.3 (4 new inactive rows) → Task 1, Step 3 (`_NEW_PLANS` insert).
- Spec §2.4 (plans 7/8 untouched) → Task 1's migration never references ids 7/8.
- Spec §2.5 (Unlimited, bilingual) → Task 2, Steps 3-4.
- Spec §2.6 (trip category + UI) → Task 2, Steps 4-6.
- Spec §3.1-3.2 (scope, screens/namespace) → Task 3, Steps 4-6.
- Spec §3.3 (price-edit FSM) → Task 3, Step 6 (`manage_plan_edit_price_cb`/`manage_plan_receive_price`).
- Spec §3.4 (active toggle hides from Buy/Renew) → Task 3, Step 6 (`manage_plan_toggle_active_cb`) + Task 3's `test_toggle_active_hides_plan_from_buy_flow`.
- Spec §3.5 (audit log) → Task 3, Step 6 (`logger.info("admin_price_change", ...)`).
- Spec §3.6 (payment snapshot guarantee) → Task 3's `test_price_change_does_not_affect_existing_payment_amount`.
- Spec §5 (testing) → covered across all three tasks' test files.

**2. Placeholder scan:** The two `...` placeholders in Task 2 Step 7's
`test_renew_flow.py` sketch and Task 3 Step 1's payment-mocking note are
intentional, explicit instructions to match an existing file's pattern
rather than guessing it blind — both name exactly which file's existing
tests to copy from, so they are not vague "add tests" placeholders. No
other placeholder language appears.

**3. Type consistency:** `format_data_cap(data_cap_mb: int, lang: str) -> str`
is defined once in Task 2 Step 4 and every call site across Task 2
(Steps 6-7) and Task 3 (Step 4's `plan_detail_text`, passing `"en"`
literally) matches that exact signature. Every `t()` key referenced —
`data_cap_unlimited`, `category_trip` — is added in Task 2 Step 3 before
Task 2 Step 4 uses them, and Task 3 never calls `t()` at all (admin-only,
per Global Constraints). `manage_plans_list_keyboard`,
`manage_plans_detail_keyboard`, `manage_plans_price_edit_cancel_keyboard`,
and `plan_detail_text` are defined once in Task 3 Step 4 and consumed
with matching signatures in Task 3 Step 6's handlers.
