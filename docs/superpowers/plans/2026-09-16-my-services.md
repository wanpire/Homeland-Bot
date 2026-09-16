# My Services (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the `menu:myservices` placeholder with a list of every VPN service a user has ever owned (live status badge per row), a per-service detail screen (live expiry + live-refetched credentials), and a "Resend Setup" action reusing the existing tutorial-delivery infrastructure.

**Architecture:** One new router (`app/bot/handlers/myservices.py`) + one new keyboard module (`app/bot/keyboards/myservices.py`), wired into `app/main.py`'s `build_dispatcher`. Four new small service functions in `app/services/vpn_users.py` (status computation + ownership-scoped lookups). No FSM state — every screen is reachable from a `vpn_user_id`/`protocol_id`/`platform_id` embedded in callback_data, matching Buy Subscription's and the trial flow's stateless parts.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async (same as the rest of the repo). No new dependencies, no migration.

**Spec:** `docs/superpowers/specs/2026-09-16-my-services-design.md`

## Global Constraints

- Async only — no blocking I/O in handlers or services (CLAUDE.md).
- Type hints on every function signature (CLAUDE.md).
- All user-facing strings in English (CLAUDE.md).
- Keep handlers thin: parse input, call a service, reply (CLAUDE.md).
- Every interactive flow/menu includes a "Back" button by default (CLAUDE.md).
- `app/main.py`'s `build_dispatcher(storage)` is the single source of truth for router wiring.
- Callback-data namespace is `myservices:*`, colon-separated, matching the existing `menu:*`/`buy:*`/`trial:*`/`adm:*` convention.
- `get_service_status` must never raise — a status-check failure must never crash the screen showing it; it returns `("unknown", None)` instead (spec §4).
- Every screen keyed by a `vpn_user_id` from callback_data must verify that row belongs to the requesting `telegram_id` (`get_owned_vpn_user`) — a row that exists but belongs to someone else is treated identically to "not found," never leaking another customer's plan/credentials.
- `plan.name`/`vpn_user.ibsng_group`/`vpn_user.ibsng_username` are catalog/generator-controlled, not user-typed — no `html.escape()` needed (spec §5), unlike admin-typed or external text elsewhere in the bot.
- Resend Setup calls `deliver_setup` only — it never re-sends account credentials (the detail screen already showed them).

---

## File Structure

New files:
- `app/bot/keyboards/myservices.py` — `myservices_empty_keyboard()`, `myservices_list_keyboard(rows)`, `myservices_detail_keyboard(vpn_user_id)` (Task 1); `myservices_protocol_keyboard(protocols, vpn_user_id)`, `myservices_platform_keyboard(platforms, vpn_user_id, protocol_id)` (Task 2).
- `app/bot/handlers/myservices.py` — `menu:myservices` / `myservices:view:*` handlers (Task 1); `myservices:resend:*` handler (Task 2).
- `tests/functional/test_myservices_flow.py`

Modified files:
- `app/services/vpn_users.py` — add `parse_ibsng_expiry`, `get_service_status`, `get_owned_vpn_user`, `list_vpn_users_for_telegram_id` (Task 1).
- `app/bot/handlers/users.py` — remove `"menu:myservices"` from `_PLACEHOLDER_CALLBACKS` (Task 1).
- `app/main.py` — register `myservices.router` (Task 1).
- `tests/functional/test_start_and_menu.py` — drop `"menu:myservices"` from the placeholder-callback test (Task 1).

---

### Task 1: List + detail screens

**Files:**
- Modify: `app/services/vpn_users.py`
- Create: `app/bot/keyboards/myservices.py`
- Create: `app/bot/handlers/myservices.py`
- Modify: `app/bot/handlers/users.py`
- Modify: `app/main.py`
- Modify: `tests/functional/test_start_and_menu.py`
- Test: `tests/functional/test_myservices_flow.py`

**Interfaces:**
- Consumes: `catalog.get_plan(session, plan_id) -> Plan | None` (existing). `IBSngClient.get_user_expiry(username)`, `get_user_password(username)` (existing, `app/services/ibsng/client.py`). `back_to_menu_keyboard()` from `app.bot.keyboards.trial` (existing, already reused by `users.py`'s support handler and `buy.py`'s not-found screens).
- Produces: `parse_ibsng_expiry(raw: str) -> dt.datetime | None`, `get_service_status(client: IBSngClient, username: str) -> tuple[str, dt.datetime | None]`, `get_owned_vpn_user(session, vpn_user_id, telegram_id) -> VPNUser | None`, `list_vpn_users_for_telegram_id(session, telegram_id) -> list[VPNUser]` (all `app/services/vpn_users.py`) — Task 2's resend handler consumes `get_owned_vpn_user` by name.

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_myservices_flow.py`:

```python
from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


async def _create_service(seeded_catalog: dict, *, telegram_id: int, category: str, name: str, is_trial: bool = False):
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    plan = next(p for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        vpn_user = await create_vpn_user(
            session, client, telegram_id=telegram_id, username=username, password=password,
            group_name=plan["group_name"], data_cap_mb=plan["data_cap_mb"], plan_id=plan["id"], is_trial=is_trial,
        )
    return vpn_user


@pytest.mark.asyncio
async def test_myservices_shows_empty_state_when_no_services(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(701, "menu:myservices"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "don't have any services" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔑 Buy Subscription" in buttons
    assert "🎁 Free Trial" in buttons


@pytest.mark.asyncio
async def test_myservices_lists_services_with_status_badges(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    telegram_id = 702
    active = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    expired = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="2 Weeks")
    pending = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(active.ibsng_username, "nearest_exp_date", future)
    ibsng_server.set_user_attr(expired.ibsng_username, "nearest_exp_date", past)
    # pending: leave unset - the fake server's default has no nearest_exp_date

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "menu:myservices"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    texts = [b["text"] for b in buttons]
    assert "1 Month — ✅ Active" in texts
    assert "2 Weeks — ⛔ Expired" in texts
    assert sum(1 for t in texts if t.startswith("1 Month — ⏳ Pending")) == 1

    callback_by_text = {b["text"]: b["callback_data"] for b in buttons}
    assert callback_by_text["1 Month — ✅ Active"] == f"myservices:view:{active.id}"
    assert callback_by_text["2 Weeks — ⛔ Expired"] == f"myservices:view:{expired.id}"


@pytest.mark.asyncio
async def test_myservices_detail_shows_plan_status_and_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    telegram_id = 703
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(service.ibsng_username, "nearest_exp_date", future)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "1 Month" in text
    assert "✅ Active until" in text
    assert service.ibsng_username in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔄 Resend Setup" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_myservices_detail_shows_pending_status(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 704
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not yet activated" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_view_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 705
    intruder_id = 706
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()
    assert service.ibsng_username not in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_myservices_view_unknown_id_shows_not_found(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(707, "myservices:view:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_menu_myservices_is_no_longer_a_placeholder(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(708, "menu:myservices"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("coming soon" in c[1].get("text", "").lower() for c in answered)
```

Also edit `tests/functional/test_start_and_menu.py`'s `test_placeholder_callbacks_answer_coming_soon`: remove `"menu:myservices"` from the tuple:

```python
    for callback_data in (
        "menu:renew",
        "menu:tutorials",
    ):
```
(keep the rest of the function body unchanged.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (target `tests/functional/test_myservices_flow.py`)
Expected: FAIL — `menu:myservices` still answers "coming soon"; `myservices:view:*` has no handler at all.

- [ ] **Step 3: Add the status/ownership helpers to `vpn_users.py`**

In `app/services/vpn_users.py`, change the imports at the top to:

```python
from __future__ import annotations

import datetime as dt
import secrets
import string

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vpn_user import VPNUser
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
```

and add at the end of the file (after `renew_and_change_group`):

```python
def parse_ibsng_expiry(raw: str) -> dt.datetime | None:
    """IBSng's nearest_exp_date reads None until an account's first
    connection starts the countdown; once set, confirmed live (on this
    shared instance, via the sibling AloBot project) as "YYYY-MM-DD HH:MM"
    (e.g. "2026-09-23 15:41"). Defensively tries that shape plus a couple
    of common fallbacks, and returns None (treat as unknown, don't crash)
    rather than guess on an unrecognized format."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


async def get_service_status(client: IBSngClient, username: str) -> tuple[str, dt.datetime | None]:
    """Never raises - a status check failing must never crash the screen
    showing it. Returns ("unknown", None) on any IBSng error or
    unparseable date, ("pending", None) when IBSng has no expiry yet
    (never connected), else ("active"|"expired", the parsed datetime)."""
    try:
        raw = await client.get_user_expiry(username=username)
    except IBSngError:
        return "unknown", None
    if not raw:
        return "pending", None
    expiry = parse_ibsng_expiry(raw)
    if expiry is None:
        return "unknown", None
    now = dt.datetime.now(dt.timezone.utc)
    return ("active" if expiry > now else "expired"), expiry


async def get_owned_vpn_user(session: AsyncSession, vpn_user_id: int, telegram_id: int) -> VPNUser | None:
    return (
        await session.execute(
            select(VPNUser).where(VPNUser.id == vpn_user_id, VPNUser.telegram_id == telegram_id)
        )
    ).scalar_one_or_none()


async def list_vpn_users_for_telegram_id(session: AsyncSession, telegram_id: int) -> list[VPNUser]:
    return list(
        (
            await session.execute(
                select(VPNUser).where(VPNUser.telegram_id == telegram_id).order_by(VPNUser.id)
            )
        )
        .scalars()
        .all()
    )
```

- [ ] **Step 4: Create the My Services keyboards module**

`app/bot/keyboards/myservices.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser

_STATUS_BADGE = {
    "active": "✅ Active",
    "expired": "⛔ Expired",
    "pending": "⏳ Pending",
    "unknown": "⚠️ Unknown",
}


def myservices_empty_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Buy Subscription", callback_data="menu:buy", style="success")
    builder.button(text="🎁 Free Trial", callback_data="menu:trial", style="success")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def myservices_list_keyboard(rows: list[tuple[VPNUser, Plan | None, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan, status in rows:
        name = plan.name if plan is not None else vpn_user.ibsng_group
        builder.button(
            text=f"{name} — {_STATUS_BADGE[status]}",
            callback_data=f"myservices:view:{vpn_user.id}",
        )
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def myservices_detail_keyboard(vpn_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Resend Setup", callback_data=f"myservices:resend:{vpn_user_id}")
    builder.button(text="⬅️ Back to List", callback_data="menu:myservices")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Create the My Services handler (list + detail)**

`app/bot/handlers/myservices.py`:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.myservices import myservices_detail_keyboard, myservices_empty_keyboard, myservices_list_keyboard
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import get_plan
from app.services.ibsng.client import IBSngClient
from app.services.vpn_users import get_owned_vpn_user, get_service_status, list_vpn_users_for_telegram_id

router = Router(name="myservices")

_LIST_TEXT = "🛍 <b>My Services</b>"
_EMPTY_TEXT = "🛍 <b>My Services</b>\n\nYou don't have any services yet."
_NOT_FOUND_TEXT = "⚠️ That service wasn't found."


@router.callback_query(F.data == "menu:myservices")
async def myservices_list_cb(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        vpn_users = await list_vpn_users_for_telegram_id(session, telegram_id)
        if not vpn_users:
            if callback.message is not None:
                await callback.message.edit_text(_EMPTY_TEXT, reply_markup=myservices_empty_keyboard())
            await callback.answer()
            return

        rows: list[tuple[VPNUser, Plan | None, str]] = []
        async with IBSngClient() as client:
            for vpn_user in vpn_users:
                plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
                status, _ = await get_service_status(client, vpn_user.ibsng_username)
                rows.append((vpn_user, plan, status))

    if callback.message is not None:
        await callback.message.edit_text(_LIST_TEXT, reply_markup=myservices_list_keyboard(rows))
    await callback.answer()


async def _detail_text(session: AsyncSession, client: IBSngClient, vpn_user: VPNUser) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    name = plan.name if plan is not None else vpn_user.ibsng_group
    status, expiry = await get_service_status(client, vpn_user.ibsng_username)

    if status == "active":
        status_line = f"Status: ✅ Active until {expiry:%Y-%m-%d %H:%M} UTC"
    elif status == "expired":
        status_line = f"Status: ⛔ Expired on {expiry:%Y-%m-%d %H:%M} UTC"
    elif status == "pending":
        status_line = "Status: ⏳ Not yet activated — validity starts on first connection."
    else:
        status_line = "Status: ⚠️ Couldn't check status right now."

    password = await client.get_user_password(username=vpn_user.ibsng_username)
    password_line = (
        f"Password: <code>{password}</code>" if password is not None else "Password: unavailable — contact support"
    )

    return (
        f"🔑 <b>{name}</b>\n"
        f"{status_line}\n\n"
        f"Username: <code>{vpn_user.ibsng_username}</code>\n"
        f"{password_line}"
    )


@router.callback_query(F.data.startswith("myservices:view:"))
async def myservices_view_cb(callback: CallbackQuery) -> None:
    vpn_user_id = int(callback.data.split(":")[-1])
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            if callback.message is not None:
                await callback.message.edit_text(_NOT_FOUND_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return
        async with IBSngClient() as client:
            text = await _detail_text(session, client, vpn_user)

    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user.id))
    await callback.answer()
```

- [ ] **Step 6: Wire the router into `app/main.py` and unblock `menu:myservices`**

In `app/bot/handlers/users.py`, remove `"menu:myservices"` from `_PLACEHOLDER_CALLBACKS`:

```python
_PLACEHOLDER_CALLBACKS = {
    "menu:renew",
    "menu:tutorials",
}
```

In `app/main.py`, change:
```python
from app.bot.handlers import (
    admin, admin_block, admin_discounts, admin_fallback, admin_renew, admin_settings,
    broadcast, buy, fallback, trial, tutorial_admin, users,
)
```
to:
```python
from app.bot.handlers import (
    admin, admin_block, admin_discounts, admin_fallback, admin_renew, admin_settings,
    broadcast, buy, fallback, myservices, trial, tutorial_admin, users,
)
```

and change:
```python
    dp.include_router(buy.router)
    dp.include_router(users.router)
```
to:
```python
    dp.include_router(buy.router)
    dp.include_router(myservices.router)
    dp.include_router(users.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_myservices_flow.py`'s Task-1 tests, and the updated `test_start_and_menu.py`.

- [ ] **Step 8: Commit**

```bash
git add app/services/vpn_users.py app/bot/keyboards/myservices.py app/bot/handlers/myservices.py \
        app/bot/handlers/users.py app/main.py \
        tests/functional/test_myservices_flow.py tests/functional/test_start_and_menu.py
git commit -m "feat: my services list and detail screens"
```

---

### Task 2: Resend Setup

**Files:**
- Modify: `app/bot/keyboards/myservices.py`
- Modify: `app/bot/handlers/myservices.py`
- Test: `tests/functional/test_myservices_flow.py`

**Interfaces:**
- Consumes: `get_owned_vpn_user` from `app.services.vpn_users` (Task 1). `tutorials.list_protocols`/`list_platforms` (existing, already used by `trial.py`). `tutorial_delivery.deliver_setup(bot, telegram_id, session, *, protocol_id, platform_id) -> tuple[bool, int | None]` (existing).
- Produces: nothing consumed by a later task — this is the plan's last task.

- [ ] **Step 1: Write the failing tests**

Append to `tests/functional/test_myservices_flow.py`:

```python
@pytest.mark.asyncio
async def test_myservices_resend_shows_protocol_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 710
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "which protocol" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "OpenVPN" in buttons
    assert "L2TP" in buttons


@pytest.mark.asyncio
async def test_myservices_resend_openvpn_delivers_directly_without_platform_step(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_protocol import TutorialProtocol

    telegram_id = 711
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        openvpn_id = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))
        ).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}"))
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:protocol:{openvpn_id}")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "sent" in edited[-1][1]["text"].lower()
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔄 Resend Setup" in buttons


@pytest.mark.asyncio
async def test_myservices_resend_l2tp_shows_platform_picker_then_delivers(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    telegram_id = 712
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        ios_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}"))
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:protocol:{l2tp_id}")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "which device" in edited[-1][1]["text"].lower()

    fake_session.reset()
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:platform:{l2tp_id}:{ios_id}")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "sent" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_resend_does_not_resend_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_protocol import TutorialProtocol

    telegram_id = 713
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        openvpn_id = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))
        ).scalar_one().id

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}"))
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:protocol:{openvpn_id}")
    )

    sent = [c for c in fake_session.calls if c[0] in ("sendMessage", "sendPhoto", "sendDocument", "sendVideo")]
    assert not any(
        "password" in c[1].get("text", "").lower() or "password" in c[1].get("caption", "").lower() for c in sent
    )


@pytest.mark.asyncio
async def test_myservices_resend_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 714
    intruder_id = 715
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"myservices:resend:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (target the new tests in `tests/functional/test_myservices_flow.py`)
Expected: FAIL — `myservices:resend:*` has no handler yet.

- [ ] **Step 3: Add the protocol/platform keyboards**

In `app/bot/keyboards/myservices.py`, add the following import at the top:

```python
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
```

and these two functions at the end of the file:

```python
def myservices_protocol_keyboard(protocols: list[TutorialProtocol], vpn_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"myservices:resend:{vpn_user_id}:protocol:{protocol.id}")
    builder.button(text="⬅️ Back to Service", callback_data=f"myservices:view:{vpn_user_id}")
    builder.adjust(2, 1)
    return builder.as_markup()


def myservices_platform_keyboard(
    platforms: list[TutorialPlatform], vpn_user_id: int, protocol_id: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(
            text=platform.label,
            callback_data=f"myservices:resend:{vpn_user_id}:platform:{protocol_id}:{platform.id}",
        )
    builder.button(text="⬅️ Back", callback_data=f"myservices:resend:{vpn_user_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
```

- [ ] **Step 4: Add the resend handler**

In `app/bot/handlers/myservices.py`, change the imports at the top to:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.myservices import (
    myservices_detail_keyboard,
    myservices_empty_keyboard,
    myservices_list_keyboard,
    myservices_platform_keyboard,
    myservices_protocol_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import get_plan
from app.services.ibsng.client import IBSngClient
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols
from app.services.vpn_users import get_owned_vpn_user, get_service_status, list_vpn_users_for_telegram_id
```

and add these constants next to the existing ones (`_NOT_FOUND_TEXT` etc.):

```python
_PROTOCOL_PROMPT_TEXT = "🔌 Which protocol do you want to use?"
_PLATFORM_PROMPT_TEXT = "📱 Which device do you want to set it up on?"
_RESENT_TEXT = "✅ Sent — check the message above."
_RESEND_BLOCKED_TEXT = "⚠️ See the message above for details."
```

and add this handler at the end of the file:

```python
@router.callback_query(F.data.startswith("myservices:resend:"))
async def myservices_resend_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    vpn_user_id = int(parts[2])
    telegram_id = callback.from_user.id

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            if callback.message is not None:
                await callback.message.edit_text(_NOT_FOUND_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

        if len(parts) == 3:
            # myservices:resend:<id> - entry point, show the protocol picker.
            protocols = await list_protocols(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    _PROTOCOL_PROMPT_TEXT, reply_markup=myservices_protocol_keyboard(protocols, vpn_user_id)
                )
            await callback.answer()
            return

        if parts[3] == "protocol":
            protocol_id = int(parts[4])
            protocol = await session.get(TutorialProtocol, protocol_id)
            if protocol is not None and protocol.label.strip().lower() == "openvpn":
                delivered, _ = await deliver_setup(
                    callback.bot, telegram_id, session, protocol_id=protocol_id, platform_id=None
                )
                text = _RESENT_TEXT if delivered else _RESEND_BLOCKED_TEXT
                if callback.message is not None:
                    await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user_id))
                await callback.answer()
                return

            platforms = await list_platforms(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    _PLATFORM_PROMPT_TEXT,
                    reply_markup=myservices_platform_keyboard(platforms, vpn_user_id, protocol_id),
                )
            await callback.answer()
            return

        # parts[3] == "platform": myservices:resend:<id>:platform:<protocol_id>:<platform_id>
        protocol_id = int(parts[4])
        platform_id = int(parts[5])
        delivered, _ = await deliver_setup(
            callback.bot, telegram_id, session, protocol_id=protocol_id, platform_id=platform_id
        )
        text = _RESENT_TEXT if delivered else _RESEND_BLOCKED_TEXT
        if callback.message is not None:
            await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user_id))
        await callback.answer()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_myservices_flow.py`, and the full suite green from a fresh state.

- [ ] **Step 6: Commit**

```bash
git add app/bot/keyboards/myservices.py app/bot/handlers/myservices.py tests/functional/test_myservices_flow.py
git commit -m "feat: my services resend-setup flow"
```

---

## Self-Review

**Spec coverage** (`docs/superpowers/specs/2026-09-16-my-services-design.md`):
- §1 Summary / four-state status → Task 1 (`get_service_status`).
- §2 Navigation (`myservices:*`, ownership check, Back on every screen) → Tasks 1 and 2 together.
- §3 List screen → Task 1.
- §4 Service status + ownership helpers → Task 1.
- §5 Detail screen → Task 1.
- §6 Resend Setup → Task 2.
- §7 Out of scope (live usage/quota, renew/cancel, changes to other flows) → deliberately not built anywhere in this plan, matching the spec.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code; no test asserts a tautology.

**Type consistency check:**
- `get_service_status(client: IBSngClient, username: str) -> tuple[str, dt.datetime | None]` (Task 1) is called identically in both the list loop and `_detail_text` (Task 1), and its four possible first-element values (`"active"|"expired"|"pending"|"unknown"`) match `_STATUS_BADGE`'s keys in `myservices_list_keyboard` (Task 1) and the four-way branch in `_detail_text` (Task 1) exactly.
- `get_owned_vpn_user(session, vpn_user_id, telegram_id) -> VPNUser | None` (Task 1) is consumed identically by `myservices_view_cb` (Task 1) and `myservices_resend_cb` (Task 2) — same ownership semantics, same not-found handling.
- `myservices_protocol_keyboard`/`myservices_platform_keyboard` (Task 2) embed `vpn_user_id` in every callback_data they produce, matching the parsing (`parts[2]`) `myservices_resend_cb` (Task 2) expects.
