from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin_settings import back_to_settings_keyboard, settings_edit_cancel_keyboard
from app.bot.states.admin_settings import EditMandatoryChannelStates, EditReminderStates, EditSupportStates
from app.db.session import async_session_maker
from app.services.app_config import get_config, set_config
from app.services.groups import sync_groups
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.reminders import DEFAULT_DAYS_BEFORE
from app.services.mandatory_channel import (
    get_mandatory_channels,
    is_mandatory_channel_enabled,
    set_mandatory_channel_enabled,
    set_mandatory_channels,
)

router = Router(name="admin_settings")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

_SUPPORT_PROMPT_TEXT = "Send the support contact (e.g. @homeland_support):"
_EMPTY_SUPPORT_TEXT = "⚠️ Send a non-empty value."
_SYNC_FAILED_TEXT = "⚠️ Could not reach IBSng to sync groups. Please try again shortly."


@router.callback_query(F.data == "adm:settings:support")
async def settings_edit_support_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditSupportStates.support_username)
    if callback.message is not None:
        await callback.message.edit_text(_SUPPORT_PROMPT_TEXT, reply_markup=settings_edit_cancel_keyboard())
    await callback.answer()


@router.message(EditSupportStates.support_username)
async def settings_receive_support_username(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer(_EMPTY_SUPPORT_TEXT, reply_markup=settings_edit_cancel_keyboard())
        return
    async with async_session_maker() as session:
        await set_config(session, "support_username", value)
    await state.clear()
    await message.answer(f"✅ Support contact set to {html.escape(value)}.", reply_markup=back_to_settings_keyboard())


@router.callback_query(F.data == "adm:settings:syncgroups")
async def settings_sync_groups_cb(callback: CallbackQuery) -> None:
    try:
        async with async_session_maker() as session, IBSngClient() as client:
            groups = await sync_groups(session, client)
    except IBSngError:
        if callback.message is not None:
            await callback.message.edit_text(_SYNC_FAILED_TEXT, reply_markup=back_to_settings_keyboard())
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(
            f"🔄 Synced {len(groups)} Homeland group(s).", reply_markup=back_to_settings_keyboard()
        )
    await callback.answer()


_CHANNEL_PROMPT_TEXT = (
    "Send the channel username(s) to require, comma-separated, without @ "
    "(e.g. homeland_channel, homeland_news). Send \"clear\" to remove all."
)
_EMPTY_CHANNELS_TEXT = "⚠️ Send a non-empty value."
_USERNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


async def _channel_status_text(session: AsyncSession) -> str:
    channels = await get_mandatory_channels(session)
    enabled = await is_mandatory_channel_enabled(session)
    state_line = "🟢 Enabled" if enabled else "🔴 Disabled"
    channels_line = ", ".join(f"@{html.escape(c)}" for c in channels) if channels else "(none set)"
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
            invalid = [u for u in usernames if not _USERNAME_PATTERN.match(u)]
            if invalid:
                await message.answer(
                    f"⚠️ Not a valid Telegram username: {html.escape(invalid[0])} "
                    "(letters, numbers, underscores, 5-32 characters, starting with a letter). "
                    "Send a channel username, not an ID or link.",
                    reply_markup=settings_edit_cancel_keyboard(),
                )
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
