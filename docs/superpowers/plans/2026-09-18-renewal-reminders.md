# Renewal Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send Homeland VPN customers a Telegram reminder shortly before their service expires, and let a full admin turn this on/off and adjust the days-before threshold.

**Architecture:** A plain `asyncio` background task (`run_reminder_loop`), started alongside the bot's polling loop in `app/main.py`, wakes every 30 minutes and calls `send_due_reminders`, which queries non-trial `VPNUser` rows not yet reminded this cycle, asks IBSng for each one's live expiry via the already-existing `get_service_status` helper, and DMs anyone inside the admin-configured window. A fourth entry is added to the existing admin Settings menu, mirroring the Mandatory Channel feature's exact status/edit/toggle screen pattern.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, the existing free-form `app_config` key/value store (no schema changes, no new dependency).

**Spec:** `docs/superpowers/specs/2026-09-18-renewal-reminders-design.md`

## Global Constraints

- Scope is expiry reminders only. Low-quota reminders are out of scope for this plan — no working IBSng data source exists (`user_balance.getUserBalanceInfoByUserID` is confirmed dead on this server).
- No new dependency. The background job is a plain `asyncio.create_task(...)` loop, matching AloBot's proven `app/services/reminders.py` — do not add a scheduler library to `requirements.txt`.
- The 30-minute check interval (`_CHECK_INTERVAL_SECONDS = 30 * 60`) is a fixed constant, not admin-configurable.
- `reminder_enabled` has one special semantic: an **unset** config value (`get_config` returns `None`) must be treated as **enabled**. This is the only place in this feature where "missing config" and "explicitly true" behave identically — everywhere else in this project, missing config means the disabled/empty state.
- Reuse `get_service_status(client, username) -> tuple[str, dt.datetime | None]` (`app/services/vpn_users.py:163`) for expiry lookups — do not re-derive expiry parsing inline. Only `status == "active"` with a non-`None` expiry is ever eligible for a reminder.
- `app/main.py`'s background task must be cancelled on shutdown: `reminder_task.cancel()` added to the existing `finally:` block, alongside the pre-existing `runner.cleanup()` and `bot.session.close()`.
- All user-facing and admin-facing strings in English, per this project's CLAUDE.md.

---

## File Structure

- **Create** `app/services/reminders.py` — the reminder job: `send_due_reminders(bot)` (one pass) and `run_reminder_loop(bot)` (the `while True` wrapper), plus the public `DEFAULT_DAYS_BEFORE` constant the admin UI also reads.
- **Modify** `app/main.py` — import `run_reminder_loop`, start it as a background task, cancel it on shutdown.
- **Modify** `app/bot/states/admin_settings.py` — add `EditReminderStates` (state: `days_before`).
- **Modify** `app/bot/handlers/admin_settings.py` — add the status/edit/toggle handler trio for `adm:settings:reminders*`.
- **Modify** `app/bot/keyboards/admin.py` — add the "⏰ Renewal Reminders" entry to `admin_settings_menu()`.
- **Create** `tests/functional/test_reminders.py` — service-layer tests for the job.
- **Modify** `tests/functional/test_admin_settings.py` — add tests for the new admin UI screens, alongside the existing support/sync/channel tests.

---

## Task 1: Reminders service, background loop, and process wiring

**Files:**
- Create: `app/services/reminders.py`
- Modify: `app/main.py`
- Test: `tests/functional/test_reminders.py`

**Interfaces:**
- Consumes: `get_service_status(client: IBSngClient, username: str) -> tuple[str, dt.datetime | None]` from `app/services/vpn_users.py`; `get_config(session, key) -> str | None` / `set_config(session, key, value)` from `app/services/app_config.py`; `IBSngClient` from `app/services/ibsng/client.py`; `VPNUser` from `app/db/models/vpn_user.py` (fields used: `telegram_id`, `ibsng_username`, `is_trial`, `expiry_reminder_sent_at`).
- Produces: `DEFAULT_DAYS_BEFORE: int` (public constant, Task 2 imports this), `async def send_due_reminders(bot: Bot) -> None`, `async def run_reminder_loop(bot: Bot) -> None` — both consumed by `app/main.py` in this task, and `DEFAULT_DAYS_BEFORE` consumed by Task 2's admin UI.

- [ ] **Step 1: Write the failing tests for `send_due_reminders`**

Create `tests/functional/test_reminders.py`:

```python
from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.fakes.fake_bot_session import FakeBotSession


async def _seed_vpn_user(
    telegram_id: int, *, is_trial: bool = False, expiry_reminder_sent_at: dt.datetime | None = None
) -> None:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(
            VPNUser(
                telegram_id=telegram_id,
                ibsng_username=f"hl.rem{telegram_id}",
                ibsng_group="Trial-Iran",
                data_cap_mb=1024,
                is_trial=is_trial,
                expiry_reminder_sent_at=expiry_reminder_sent_at,
            )
        )
        await session.commit()


def _patch_status(monkeypatch: pytest.MonkeyPatch, status: str, expiry: dt.datetime | None) -> None:
    from app.services import reminders

    async def _fake_get_service_status(client: object, username: str) -> tuple[str, dt.datetime | None]:
        return status, expiry

    monkeypatch.setattr(reminders, "get_service_status", _fake_get_service_status)


def _sent(fake_session: FakeBotSession) -> list[tuple[str, dict[str, Any]]]:
    return [c for c in fake_session.calls if c[0] == "sendMessage"]


@pytest.mark.asyncio
async def test_sends_reminder_for_user_within_default_window(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(701)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)

    await send_due_reminders(bot)

    sent = _sent(fake_session)
    assert len(sent) == 1
    assert sent[0][1]["chat_id"] == 701
    assert "expires" in sent[0][1]["text"].lower()
    buttons = [b for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["text"] == "♻️ Renew Now" and b["callback_data"] == "menu:renew" for b in buttons)


@pytest.mark.asyncio
async def test_stamps_expiry_reminder_sent_at(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(702)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)

    await send_due_reminders(bot)

    async with async_session_maker() as session:
        vpn_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 702))).scalar_one()
    assert vpn_user.expiry_reminder_sent_at is not None


@pytest.mark.asyncio
async def test_does_not_send_when_disabled(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.app_config import set_config
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(703)
    _patch_status(monkeypatch, "active", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    async with async_session_maker() as session:
        await set_config(session, "reminder_enabled", "false")

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
async def test_unset_reminder_enabled_defaults_to_enabled(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.app_config import get_config
    from app.services.reminders import send_due_reminders

    async with async_session_maker() as session:
        assert await get_config(session, "reminder_enabled") is None

    await _seed_vpn_user(704)
    _patch_status(monkeypatch, "active", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))

    await send_due_reminders(bot)

    assert len(_sent(fake_session)) == 1


@pytest.mark.asyncio
async def test_skips_user_already_reminded_this_cycle(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(705, expiry_reminder_sent_at=dt.datetime.now(dt.timezone.utc))
    _patch_status(monkeypatch, "active", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
async def test_skips_trial_accounts(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(706, is_trial=True)
    _patch_status(monkeypatch, "active", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "unknown", "expired"])
async def test_skips_non_active_status(
    status: str, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(707)
    expiry = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1) if status == "expired" else None
    _patch_status(monkeypatch, status, expiry)

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
async def test_skips_user_outside_default_window(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(708)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)
    _patch_status(monkeypatch, "active", expiry)

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
async def test_respects_configured_days_before_threshold(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.app_config import set_config
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(709)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=4)
    _patch_status(monkeypatch, "active", expiry)
    async with async_session_maker() as session:
        await set_config(session, "reminder_days_before", "5")

    await send_due_reminders(bot)

    assert len(_sent(fake_session)) == 1


@pytest.mark.asyncio
async def test_one_users_send_failure_does_not_abort_the_batch(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(710)
    await _seed_vpn_user(711)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)
    fake_session.blocked_chat_ids.add(710)

    await send_due_reminders(bot)

    sent = _sent(fake_session)
    assert len(sent) == 1
    assert sent[0][1]["chat_id"] == 711

    async with async_session_maker() as session:
        blocked_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 710))).scalar_one()
        delivered_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 711))).scalar_one()
    assert blocked_user.expiry_reminder_sent_at is None
    assert delivered_user.expiry_reminder_sent_at is not None


@pytest.mark.asyncio
async def test_run_reminder_loop_calls_send_due_reminders_each_iteration(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import reminders

    calls: list[object] = []

    async def _fake_send_due_reminders(bot: object) -> None:
        calls.append(bot)

    class _StopLoop(Exception):
        pass

    async def _fake_sleep(seconds: float) -> None:
        raise _StopLoop()

    monkeypatch.setattr(reminders, "send_due_reminders", _fake_send_due_reminders)
    monkeypatch.setattr(reminders.asyncio, "sleep", _fake_sleep)

    fake_bot = object()
    with pytest.raises(_StopLoop):
        await reminders.run_reminder_loop(fake_bot)  # type: ignore[arg-type]

    assert calls == [fake_bot]


@pytest.mark.asyncio
async def test_run_reminder_loop_survives_an_iteration_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import reminders

    calls: list[object] = []

    async def _boom(bot: object) -> None:
        calls.append(bot)
        raise RuntimeError("boom")

    class _StopLoop(Exception):
        pass

    async def _fake_sleep(seconds: float) -> None:
        raise _StopLoop()

    monkeypatch.setattr(reminders, "send_due_reminders", _boom)
    monkeypatch.setattr(reminders.asyncio, "sleep", _fake_sleep)

    with pytest.raises(_StopLoop):
        await reminders.run_reminder_loop(object())  # type: ignore[arg-type]

    assert len(calls) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/functional/test_reminders.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.reminders'` (or `ImportError`).

- [ ] **Step 3: Create `app/services/reminders.py`**

```python
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.app_config import get_config
from app.services.ibsng.client import IBSngClient
from app.services.vpn_users import get_service_status

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 30 * 60
DEFAULT_DAYS_BEFORE = 2  # public: app/bot/handlers/admin_settings.py's status screen shares this default

_MESSAGE_TEMPLATE = (
    "⏰ Your VPN service (<code>{username}</code>) expires in less than "
    "{days} day(s). Renew now to avoid interruption."
)


def _renew_now_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="♻️ Renew Now", callback_data="menu:renew")
    builder.adjust(1)
    return builder.as_markup()


async def _reminder_window(session: AsyncSession) -> dt.timedelta:
    raw = await get_config(session, "reminder_days_before")
    try:
        days = int(raw) if raw else DEFAULT_DAYS_BEFORE
    except ValueError:
        days = DEFAULT_DAYS_BEFORE
    return dt.timedelta(days=days)


async def send_due_reminders(bot: Bot) -> None:
    """One pass: for every non-trial VPNUser not yet reminded this cycle,
    ask IBSng (via get_service_status, which already handles every parse/
    API-failure edge case) for its live expiry, and send the reminder if
    it falls within the admin-configured window. Safe to call repeatedly -
    expiry_reminder_sent_at (cleared on renewal by renew_and_change_group)
    makes it idempotent per expiry cycle. Trial accounts are excluded -
    they aren't renewable, so a "renew via the bot" reminder wouldn't
    make sense for them."""
    async with async_session_maker() as session:
        enabled_raw = await get_config(session, "reminder_enabled")
        if enabled_raw == "false":
            return

        window = await _reminder_window(session)

        candidates = (
            await session.execute(
                select(VPNUser).where(
                    VPNUser.expiry_reminder_sent_at.is_(None), VPNUser.is_trial.is_(False)
                )
            )
        ).scalars().all()
        if not candidates:
            return

        now = dt.datetime.now(dt.timezone.utc)
        async with IBSngClient() as client:
            for vpn_user in candidates:
                status, expiry = await get_service_status(client, vpn_user.ibsng_username)
                if status != "active" or expiry is None:
                    continue
                if not (dt.timedelta(0) < (expiry - now) <= window):
                    continue

                text = _MESSAGE_TEMPLATE.format(username=vpn_user.ibsng_username, days=window.days)
                try:
                    await bot.send_message(vpn_user.telegram_id, text, reply_markup=_renew_now_keyboard())
                except Exception:
                    logger.exception("Failed to send expiry reminder to telegram_id=%s", vpn_user.telegram_id)
                    continue
                vpn_user.expiry_reminder_sent_at = now
                await session.commit()


async def run_reminder_loop(bot: Bot) -> None:
    """Started as a background asyncio task from app/main.py - no
    scheduler library, matching AloBot's own proven pattern for this
    exact job (app/services/reminders.py in the sibling telegram-bot
    project)."""
    while True:
        try:
            await send_due_reminders(bot)
        except Exception:
            logger.exception("Reminder loop iteration failed")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/functional/test_reminders.py -v`
Expected: PASS (14 tests: 11 for `send_due_reminders` + 3 parametrized `status` cases counted individually, plus 2 for `run_reminder_loop`).

- [ ] **Step 5: Wire the background task into `app/main.py`**

Add the import, alongside the existing top-level imports (insert in the existing `from app...` block, keeping alphabetical-ish grouping already present — place it near `from app.config import get_settings`):

```python
from app.services.reminders import run_reminder_loop
```

In `main()`, insert the task creation right after the webhook site starts and before the `try:` block, and add the cancel call to the existing `finally:` block:

```python
    runner = web.AppRunner(create_webhook_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
    await site.start()
    logger.info("Webhook server listening on :%s", settings.webhook_port)

    reminder_task = asyncio.create_task(run_reminder_loop(bot))

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()
        await runner.cleanup()
        await bot.session.close()
```

(Only the `reminder_task = asyncio.create_task(...)` line and the `reminder_task.cancel()` line are new; everything else already exists in the current file and must not change.)

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: PASS, no regressions. (`app/main.py` has no dedicated test file in this project — its wiring is exercised by production startup, not the test suite — so this step confirms nothing else broke.)

- [ ] **Step 7: Commit**

```bash
git add app/services/reminders.py app/main.py tests/functional/test_reminders.py
git commit -m "feat: add renewal reminder job and background loop"
```

---

## Task 2: Admin settings UI for renewal reminders

**Files:**
- Modify: `app/bot/states/admin_settings.py`
- Modify: `app/bot/handlers/admin_settings.py`
- Modify: `app/bot/keyboards/admin.py`
- Test: `tests/functional/test_admin_settings.py`

**Interfaces:**
- Consumes: `DEFAULT_DAYS_BEFORE: int` from `app.services.reminders` (Task 1); `get_config`/`set_config` from `app.services.app_config`; `back_to_settings_keyboard`/`settings_edit_cancel_keyboard` from `app.bot.keyboards.admin_settings`; the existing `router` (`Router(name="admin_settings")`, already filtered to `IsFullAdmin()`) in `app/bot/handlers/admin_settings.py`.
- Produces: callback routes `adm:settings:reminders`, `adm:settings:reminders:edit`, `adm:settings:reminders:toggle`; FSM state `EditReminderStates.days_before`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/functional/test_admin_settings.py` (add these test functions at the end of the file; no changes to the existing imports at the top are needed — they already cover everything used below):

```python
@pytest.mark.asyncio
async def test_admin_settings_menu_includes_renewal_reminders_button(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "⏰ Renewal Reminders" in buttons


@pytest.mark.asyncio
async def test_reminders_status_shows_enabled_and_default_days_when_unset(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "enabled" in text.lower()
    assert "2 day" in text.lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "✏️ Edit Days Before" in buttons
    assert "🔴 Turn Off" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_non_full_admin_cannot_access_reminders_settings(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.admin_users import add_admin

    async with async_session_maker() as session:
        await add_admin(session, 611, "sales")

    await dispatcher.feed_update(bot, make_callback_update(611, "adm:settings:reminders"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []


@pytest.mark.asyncio
async def test_reminders_edit_sets_days_before(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "5"))

    async with async_session_maker() as session:
        assert await get_config(session, "reminder_days_before") == "5"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "updated" in sent[-1][1]["text"].lower()
    assert "5 day" in sent[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_reminders_edit_rejects_non_digit_input(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "abc"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("positive whole number" in c[1].get("text", "").lower() for c in sent)

    async with async_session_maker() as session:
        assert await get_config(session, "reminder_days_before") is None


@pytest.mark.asyncio
async def test_reminders_edit_rejects_zero(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "0"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("positive whole number" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_reminders_toggle_flips_state(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:toggle"))
    async with async_session_maker() as session:
        assert await get_config(session, "reminder_enabled") == "false"
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🟢 Turn On" in buttons

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:toggle"))
    async with async_session_maker() as session:
        assert await get_config(session, "reminder_enabled") == "true"
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔴 Turn Off" in buttons
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/functional/test_admin_settings.py -v -k reminders`
Expected: FAIL — the `adm:settings:reminders*` routes don't exist yet, so `edited`/`sent` come back empty and the assertions fail (not an import error, since these tests only reach into already-existing modules).

- [ ] **Step 3: Add `EditReminderStates` to `app/bot/states/admin_settings.py`**

Add this class at the end of the file, alongside the two existing `StatesGroup` classes:

```python
class EditReminderStates(StatesGroup):
    days_before = State()
```

- [ ] **Step 4: Add the reminder settings entry to `app/bot/keyboards/admin.py`**

In `admin_settings_menu()`, insert one line after the existing `"📢 Mandatory Channel"` button and before the back button:

```python
def admin_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="☎️ Support Contact", callback_data="adm:settings:support")
    builder.button(text="🔄 Sync IBSng Groups", callback_data="adm:settings:syncgroups")
    builder.button(text="📢 Mandatory Channel", callback_data="adm:settings:channel")
    builder.button(text="⏰ Renewal Reminders", callback_data="adm:settings:reminders")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Add the reminder handlers to `app/bot/handlers/admin_settings.py`**

Update the imports at the top of the file: add `get_config` to the existing `app_config` import, add `EditReminderStates` to the existing states import, and add the new `reminders` import:

```python
from app.services.app_config import get_config, set_config
```

```python
from app.bot.states.admin_settings import EditMandatoryChannelStates, EditReminderStates, EditSupportStates
```

```python
from app.services.reminders import DEFAULT_DAYS_BEFORE
```

Append the following to the end of the file (after the existing `settings_toggle_channel_cb`):

```python
_REMINDER_DAYS_PROMPT_TEXT = "Send the number of days before expiry to send the reminder (e.g. 2):"
_INVALID_DAYS_TEXT = "⚠️ Send a positive whole number of days."


async def _reminder_status_text(session: AsyncSession) -> str:
    enabled = (await get_config(session, "reminder_enabled")) != "false"
    raw_days = await get_config(session, "reminder_days_before")
    try:
        days = int(raw_days) if raw_days else DEFAULT_DAYS_BEFORE
    except ValueError:
        days = DEFAULT_DAYS_BEFORE
    state_line = "🟢 Enabled" if enabled else "🔴 Disabled"
    return f"⏰ <b>Renewal Reminders</b>\n\nState: {state_line}\nWindow: {days} day(s) before expiry"


def _reminder_settings_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit Days Before", callback_data="adm:settings:reminders:edit")
    builder.button(
        text="🔴 Turn Off" if enabled else "🟢 Turn On", callback_data="adm:settings:reminders:toggle"
    )
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "adm:settings:reminders")
async def settings_reminders_status_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        enabled = (await get_config(session, "reminder_enabled")) != "false"
        text = await _reminder_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_reminder_settings_keyboard(enabled=enabled))
    await callback.answer()


@router.callback_query(F.data == "adm:settings:reminders:edit")
async def settings_edit_reminder_days_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditReminderStates.days_before)
    if callback.message is not None:
        await callback.message.edit_text(_REMINDER_DAYS_PROMPT_TEXT, reply_markup=settings_edit_cancel_keyboard())
    await callback.answer()


@router.message(EditReminderStates.days_before)
async def settings_receive_reminder_days(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(_INVALID_DAYS_TEXT, reply_markup=settings_edit_cancel_keyboard())
        return
    async with async_session_maker() as session:
        await set_config(session, "reminder_days_before", raw)
    await state.clear()
    async with async_session_maker() as session:
        enabled = (await get_config(session, "reminder_enabled")) != "false"
        text = await _reminder_status_text(session)
    await message.answer(
        f"✅ Reminder window updated.\n\n{text}", reply_markup=_reminder_settings_keyboard(enabled=enabled)
    )


@router.callback_query(F.data == "adm:settings:reminders:toggle")
async def settings_toggle_reminders_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        currently_enabled = (await get_config(session, "reminder_enabled")) != "false"
        await set_config(session, "reminder_enabled", "false" if currently_enabled else "true")
        enabled = not currently_enabled
        text = await _reminder_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_reminder_settings_keyboard(enabled=enabled))
    await callback.answer()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/functional/test_admin_settings.py -v -k reminders`
Expected: PASS (7 new tests).

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add app/bot/states/admin_settings.py app/bot/handlers/admin_settings.py app/bot/keyboards/admin.py tests/functional/test_admin_settings.py
git commit -m "feat: add renewal reminders admin settings UI"
```

---

## Self-Review

**1. Spec coverage:**
- §1 (Summary, scope narrowed to expiry-only) → Task 1's job only ever queries/reminds non-trial `VPNUser` rows; no quota-reading code anywhere in this plan.
- §2 (Config keys `reminder_enabled`/`reminder_days_before`, defaults) → Task 1's `send_due_reminders`/`_reminder_window` and Task 2's `_reminder_status_text`/toggle handler.
- §3 (the job itself: `send_due_reminders`, `run_reminder_loop`, `DEFAULT_DAYS_BEFORE`, default-true semantics, reuse of `get_service_status`) → Task 1, transcribed directly from the spec's §3 code block.
- §4 (`app/main.py` wiring, task creation + cancellation) → Task 1 Step 5.
- §5 (admin settings UI: status/edit/toggle trio, states, menu entry, no dedicated service module) → Task 2, transcribed directly from the spec's §5 code block.
- §6 (out of scope: low-quota reminders, configurable interval, other reminder types) → nothing in either task touches any of these; confirmed absent by construction.

**2. Placeholder scan:** No "TBD"/"TODO"/"implement later" anywhere in either task. Every step has complete, runnable code. No "similar to Task N" shortcuts — Task 2's code is fully written out rather than referencing Task 1's shape.

**3. Type consistency:**
- `DEFAULT_DAYS_BEFORE` is defined once (Task 1, public, no leading underscore) and imported by exact name in Task 2 — no private-name cross-module import (this was a real bug caught and fixed during the spec's own self-review, and re-checked here).
- `send_due_reminders(bot: Bot) -> None` and `run_reminder_loop(bot: Bot) -> None` signatures match between Task 1's definition and its `app/main.py` call site (`asyncio.create_task(run_reminder_loop(bot))`, same `bot` object `Dispatcher`/`start_polling` already use).
- Callback data strings `adm:settings:reminders`, `adm:settings:reminders:edit`, `adm:settings:reminders:toggle` are used identically across: the keyboard's own buttons (`_reminder_settings_keyboard`), each handler's `F.data ==` filter, and every test's `make_callback_update` call — verified by re-reading Task 2 Steps 4-5 side by side.
- `_reminder_status_text`/`_reminder_settings_keyboard` signatures (`session: AsyncSession -> str` / `*, enabled: bool -> InlineKeyboardMarkup`) are each defined once and called with matching arguments in all three handlers that use them (status, edit-receive, toggle).
- `EditReminderStates.days_before` is referenced identically in Task 2 Step 3 (definition), Step 5's `@router.message(EditReminderStates.days_before)` decorator, and the import line added to the handlers file.
