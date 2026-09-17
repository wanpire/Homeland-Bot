# Renewal Reminders — Design Spec

Date: 2026-09-18
Status: proposed
Parent spec: `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` §8
(Reminders) — this spec is the first concrete implementation, narrowed
to the expiry half only (see §1).

## 1. Summary

A background job that DMs a user before their VPN service expires,
pointing them at Renew Service, and records that it did so (so it never
re-sends within the same expiry cycle). Admin-configurable on/off and
days-before threshold.

**Scope narrowed from the original request:** the parent spec's §8 and
this feature's own originating request both described a *second*
reminder type — low remaining data quota. That half is **not buildable**
on this IBSng server: `app/services/ibsng/client.py`'s own module
docstring confirms `user_balance.getUserBalanceInfoByUserID` is
"CONFIRMED DEAD on this server," and My Services' own spike (shipped
earlier this session) found no working alternative, explicitly scoping
live quota reading out of that feature for the same reason. Nothing has
changed since. This spec builds expiry reminders only;
`VPNUser.low_quota_reminder_sent_at` stays unused, exactly as it already
is today, until a working quota source is ever found.

**Scheduler mechanism:** a plain `asyncio` background task
(`while True: ... await asyncio.sleep(...)`), not APScheduler. The
sibling project AloBot already has this exact feature in production at
`app/services/reminders.py`, using precisely this pattern with zero
extra dependencies — the closest possible reference implementation, and
proof a scheduling library isn't needed for one fixed-interval job. This
spec ports it, adapted to reuse Homeland's own already-proven
`get_service_status` helper (which didn't exist in AloBot) instead of
re-deriving expiry parsing inline.

## 2. Config (`app_config` table, via existing `get_config`/`set_config`)

Two string-valued keys, same free-form pattern every setting this
session has used:

- `reminder_enabled` — `"true"` or `"false"`, **default `"true"`**
  (opt-out, not opt-in — the feature's whole purpose is proactive
  retention; a fresh, never-configured deployment starts with reminders
  on. If a fresh deploy shows `reminder_enabled` unset, the code below
  must treat that as enabled, not disabled — see §3's exact check).
- `reminder_days_before` — the reminder window in whole days, as a
  string integer, default `"2"` (missing/unparseable falls back to `2`,
  never crashes the job).

## 3. The reminder job (`app/services/reminders.py`)

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
DEFAULT_DAYS_BEFORE = 2  # public: admin_settings.py's status screen shares this default

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
    """One pass: for every non-trial VPNUser not yet reminded this
    cycle, ask IBSng (via the already-proven get_service_status, which
    handles every parse/API-failure edge case) for its live expiry, and
    send the reminder if it falls within the admin-configured window.
    Safe to call repeatedly - expiry_reminder_sent_at (cleared on
    renewal by renew_and_change_group) makes it idempotent per expiry
    cycle. Trial accounts are excluded - they aren't renewable, so a
    "renew via the bot" reminder wouldn't make sense for them."""
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
    """Started as a background asyncio task from main.py - no scheduler
    library, matching AloBot's own proven pattern for this exact job."""
    while True:
        try:
            await send_due_reminders(bot)
        except Exception:
            logger.exception("Reminder loop iteration failed")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
```

**Why `get_service_status` instead of re-deriving expiry parsing:** it
already exists (`app/services/vpn_users.py`, built for My Services) and
already handles every edge case a reminder job would otherwise have to
duplicate — an `IBSngError` mid-call (`"unknown"`), no expiry yet
(`"pending"`), an unparseable date (`"unknown"`). The job only acts on
`"active"`, so all three of those cases are correctly skipped for free.

**`reminder_enabled` default-true semantics:** `get_config` returns
`None` for a key that was never set. The check `enabled_raw == "false"`
treats `None` (never configured) the same as `"true"` (explicitly
enabled) — both fall through to running the job — and only an explicit
`"false"` from the admin UI disables it. This is the one place in this
spec's code where "missing config" and "explicit true" must behave
identically; every other config value in this project defaults to the
*disabled*/empty state when unset, so this is a deliberate, called-out
exception, not an oversight.

## 4. Process wiring (`app/main.py`)

```python
    reminder_task = asyncio.create_task(run_reminder_loop(bot))

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()
        await runner.cleanup()
        await bot.session.close()
```

(`from app.services.reminders import run_reminder_loop` added to the
imports; the `reminder_task = asyncio.create_task(...)` line goes
right after the existing webhook `runner`/`site` startup block and
before `try: ... await dp.start_polling(bot)`; `reminder_task.cancel()`
added to the existing `finally` block, alongside `runner.cleanup()`.)

## 5. Admin settings UI

New handlers in `app/bot/handlers/admin_settings.py`, mirroring Phase
2's exact three-screen shape (status / edit-prompt / toggle):

Import additions to the top of `app/bot/handlers/admin_settings.py`:
`get_config` added to the existing `from app.services.app_config import
set_config` line (becomes `from app.services.app_config import
get_config, set_config`), plus a new
`from app.services.reminders import DEFAULT_DAYS_BEFORE`, plus
`EditReminderStates` added to the existing
`from app.bot.states.admin_settings import ...` line.

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
    await message.answer(f"✅ Reminder window updated.\n\n{text}", reply_markup=_reminder_settings_keyboard(enabled=enabled))


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

New FSM state (`app/bot/states/admin_settings.py`, alongside
`EditSupportStates`/`EditMandatoryChannelStates`):

```python
class EditReminderStates(StatesGroup):
    days_before = State()
```

`admin_settings_menu()` (`app/bot/keyboards/admin.py`) gains one entry,
after the existing three:

```python
    builder.button(text="⏰ Renewal Reminders", callback_data="adm:settings:reminders")
```

Note: `settings_toggle_reminders_cb`'s toggle writes the *opposite*
string directly via `set_config` (no `set_mandatory_channel_enabled`-
style dedicated setter exists for this simpler boolean-as-string-with-
missing-means-true case) — this is intentionally different from Phase
2's `is_mandatory_channel_enabled`/`set_mandatory_channel_enabled`
service-function pair, because `reminder_enabled`'s default-true-when-
missing semantics (§3) would make a matching service function's
contract more confusing than the two straightforward inline checks
shown above. Not adding a service module for this feature at all — the
config reads/writes are simple enough to stay inline in
`admin_settings.py` and `reminders.py`, each reading `get_config`
directly, matching how `settings_sync_groups_cb`'s section of this same
file already does its own inline config-less logic without a dedicated
service wrapper.

## 6. Out of scope

- Low-quota reminders — no working IBSng data source exists (§1).
- Making the 30-minute check interval itself admin-configurable — fixed,
  matching AloBot's own proven value.
- Any reminder type beyond the single expiry reminder.
- A "send a test reminder now" admin action.
