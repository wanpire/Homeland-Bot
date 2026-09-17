# Mandatory Channel Membership — Design Spec

Date: 2026-09-17
Status: proposed

## 1. Summary

Gates every bot interaction behind membership in zero or more admin-configured
public Telegram channels ("forced subscription"), a common pattern for
growing a channel's audience through a bot's user base. When enabled, a
non-member sees a join screen instead of whatever they tried to do, with a
join-link button per missing channel and a single recheck button. Admins are
always exempt, so a misconfiguration can never lock the admin panel itself.
The feature defaults to disabled and does nothing until an admin both sets at
least one channel and flips it on.

## 2. Config (`app_config` table, via existing `get_config`/`set_config`)

Two string-valued keys, following the same free-form key/value `AppConfig`
row shape every other setting already uses (no schema change):

- `mandatory_channel_usernames` — comma-separated channel usernames, without
  the leading `@` (mirrors `Settings.admin_id_list`'s own comma-list
  convention over in `app/config.py`, not `app_config`, but the same parsing
  idiom). Empty/missing means no channels configured.
- `mandatory_channel_enabled` — `"true"` or `"false"` (missing treated as
  `"false"`). The feature is a no-op unless this is `"true"` AND at least one
  channel is configured.

```python
# app/services/mandatory_channel.py

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_config import get_config, set_config

_USERNAMES_KEY = "mandatory_channel_usernames"
_ENABLED_KEY = "mandatory_channel_enabled"


async def get_mandatory_channels(session: AsyncSession) -> list[str]:
    """Returns the configured channel usernames (no leading @), or an
    empty list if none are set."""
    raw = await get_config(session, _USERNAMES_KEY)
    if not raw:
        return []
    return [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]


async def set_mandatory_channels(session: AsyncSession, usernames: list[str]) -> None:
    await set_config(session, _USERNAMES_KEY, ",".join(u.strip().lstrip("@") for u in usernames if u.strip()))


async def is_mandatory_channel_enabled(session: AsyncSession) -> bool:
    return (await get_config(session, _ENABLED_KEY)) == "true"


async def set_mandatory_channel_enabled(session: AsyncSession, enabled: bool) -> None:
    await set_config(session, _ENABLED_KEY, "true" if enabled else "false")
```

## 3. Membership check + middleware

```python
# app/bot/middlewares/mandatory_channel.py

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.bot.keyboards.mandatory_channel import join_channels_keyboard
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.mandatory_channel import get_mandatory_channels, is_mandatory_channel_enabled

logger = logging.getLogger(__name__)

_JOINED_STATUSES = {"member", "administrator", "creator", "restricted"}
_JOIN_PROMPT_TEXT = (
    "📢 <b>Join our channel to continue</b>\n\n"
    "Please join the channel(s) below, then tap \"I've Joined\"."
)


class MandatoryChannelMiddleware(BaseMiddleware):
    """Blocks every interaction for a non-member of the configured
    channel(s), when the feature is enabled. Admins are always exempt -
    a misconfigured channel must never lock the admin panel itself. A
    channel membership check that itself fails (bot not an admin of
    that channel, transient API error) fails OPEN - a broken config
    must never take down the whole bot for every user."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        inner: Message | CallbackQuery | None = event.message or event.callback_query
        if inner is None or inner.from_user is None:
            return await handler(event, data)

        user_id = inner.from_user.id
        async with async_session_maker() as session:
            if await has_level(session, user_id, "support"):
                return await handler(event, data)
            if not await is_mandatory_channel_enabled(session):
                return await handler(event, data)
            channels = await get_mandatory_channels(session)
            if not channels:
                return await handler(event, data)

        missing = [username for username in channels if not await self._is_member(inner, user_id, username)]
        if not missing:
            return await handler(event, data)

        keyboard = join_channels_keyboard(missing)
        if isinstance(inner, CallbackQuery):
            if inner.message is not None:
                await inner.message.edit_text(_JOIN_PROMPT_TEXT, reply_markup=keyboard)
            await inner.answer()
        else:
            await inner.answer(_JOIN_PROMPT_TEXT, reply_markup=keyboard)
        return None

    @staticmethod
    async def _is_member(inner: Message | CallbackQuery, user_id: int, username: str) -> bool:
        try:
            member = await inner.bot.get_chat_member(chat_id=f"@{username}", user_id=user_id)
        except TelegramAPIError as exc:
            logger.warning("Mandatory channel check failed for @%s: %s - failing open", username, exc)
            return True
        return member.status in _JOINED_STATUSES
```

```python
# app/bot/keyboards/mandatory_channel.py

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def join_channels_keyboard(missing_usernames: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for username in missing_usernames:
        builder.button(text=f"📢 Join @{username}", url=f"https://t.me/{username}")
    builder.button(text="✅ I've Joined", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

**Registration** in `app/main.py`'s `build_dispatcher`, right after `BlockedUserMiddleware` (so an already-blocked user never triggers a `get_chat_member` call):

```python
    dp.update.outer_middleware(PrivateChatOnlyMiddleware())
    dp.update.outer_middleware(UserTrackingMiddleware())
    dp.update.outer_middleware(BlockedUserMiddleware())
    dp.update.outer_middleware(MandatoryChannelMiddleware())
```

**Why the recheck button needs no dedicated handler:** `"✅ I've Joined"` uses
`callback_data="menu:root"` — an existing, already-handled callback. Tapping
it re-enters the full middleware chain; if the user has genuinely joined by
then, `MandatoryChannelMiddleware` lets it through and `menu_root_cb` (already
shipped) renders the welcome screen. If not, the same middleware blocks it
again and re-shows the identical join screen. No new state, no polling.

**Why "restricted" counts as joined:** Telegram's `ChatMemberRestricted`
status means the user is a channel member with some permissions limited
(e.g. can't post) — they are still subscribed, which is all a forced-
subscription check cares about. Only `left`/`kicked` mean "not a member."

## 4. Admin settings UI

New FSM states (`app/bot/states/admin_settings.py`, alongside the existing
`EditSupportStates`):

```python
class EditMandatoryChannelStates(StatesGroup):
    channels = State()
```

New handlers in `app/bot/handlers/admin_settings.py`, mirroring
`settings_edit_support_cb`/`settings_receive_support_username` exactly:

```python
_CHANNEL_PROMPT_TEXT = (
    "Send the channel username(s) to require, comma-separated, without @ "
    "(e.g. homeland_channel, homeland_news). Send \"clear\" to remove all."
)
_EMPTY_CHANNELS_TEXT = "⚠️ Send a non-empty value."


async def _channel_status_text(session: AsyncSession) -> str:
    channels = await get_mandatory_channels(session)
    enabled = await is_mandatory_channel_enabled(session)
    state_line = "🟢 Enabled" if enabled else "🔴 Disabled"
    channels_line = ", ".join(f"@{c}" for c in channels) if channels else "(none set)"
    return f"📢 <b>Mandatory Channel</b>\n\nState: {state_line}\nChannels: {channels_line}"


def _channel_settings_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit Channels", callback_data="adm:settings:channel:edit")
    builder.button(
        text="🔴 Turn Off" if enabled else "🟢 Turn On", callback_data="adm:settings:channel:toggle"
    )
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "adm:settings:channel")
async def settings_channel_status_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Entry point from admin_settings_menu()'s "📢 Mandatory Channel"
    button - shows current state, does not touch FSM state."""
    await state.clear()
    async with async_session_maker() as session:
        enabled = await is_mandatory_channel_enabled(session)
        text = await _channel_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_channel_settings_keyboard(enabled=enabled))
    await callback.answer()


@router.callback_query(F.data == "adm:settings:channel:edit")
async def settings_edit_channel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditMandatoryChannelStates.channels)
    if callback.message is not None:
        async with async_session_maker() as session:
            text = await _channel_status_text(session)
        await callback.message.edit_text(
            f"{text}\n\n{_CHANNEL_PROMPT_TEXT}", reply_markup=settings_edit_cancel_keyboard()
        )
    await callback.answer()


@router.message(EditMandatoryChannelStates.channels)
async def settings_receive_channels(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    async with async_session_maker() as session:
        if raw.lower() == "clear":
            await set_mandatory_channels(session, [])
        else:
            usernames = [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]
            if not usernames:
                await message.answer(_EMPTY_CHANNELS_TEXT, reply_markup=settings_edit_cancel_keyboard())
                return
            await set_mandatory_channels(session, usernames)
    await state.clear()
    async with async_session_maker() as session:
        enabled = await is_mandatory_channel_enabled(session)
        text = await _channel_status_text(session)
    await message.answer(f"✅ Channels updated.\n\n{text}", reply_markup=_channel_settings_keyboard(enabled=enabled))


@router.callback_query(F.data == "adm:settings:channel:toggle")
async def settings_toggle_channel_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        currently_enabled = await is_mandatory_channel_enabled(session)
        await set_mandatory_channel_enabled(session, not currently_enabled)
        enabled = not currently_enabled
        text = await _channel_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_channel_settings_keyboard(enabled=enabled))
    await callback.answer()
```

`admin_settings_menu()` (`app/bot/keyboards/admin.py`) gains one entry,
pointing at the status screen (`adm:settings:channel`), not directly at edit:

```python
    builder.button(text="📢 Mandatory Channel", callback_data="adm:settings:channel")
```

## 5. Out of scope

- Private channels / invite-link management — public `@username` channels
  only, per the approved design.
- Per-user "which channels has this person joined" history or analytics.
- Any UI for a user to see the channel list before being blocked (they only
  see it when an action is actually gated).
- Rate-limiting or caching `get_chat_member` calls — Telegram's own API rate
  limits apply as-is; revisit only if this becomes a measured problem.
