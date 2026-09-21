from __future__ import annotations

import datetime as dt
import html
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin_settings import (
    back_to_settings_keyboard,
    settings_edit_cancel_keyboard,
)
from app.bot.keyboards.crypto_settlement import (
    NETWORK_LABELS,
    crypto_network_choice_keyboard,
    crypto_settlement_edit_cancel_keyboard,
    crypto_settlement_status_keyboard,
)
from app.bot.keyboards.manage_plans import (
    manage_plans_detail_keyboard,
    manage_plans_list_keyboard,
    manage_plans_price_edit_cancel_keyboard,
    plan_detail_text,
)
from app.bot.states.admin_settings import (
    EditCryptoSettlementStates,
    EditMandatoryChannelStates,
    EditPlanPriceStates,
    EditReminderStates,
    EditSupportStates,
)
from app.config import get_settings
from app.db.session import async_session_maker
from app.services.app_config import get_config, set_config
from app.services.catalog import format_price_usd, get_plan, list_plans, update_plan
from app.services.groups import sync_groups
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.payments.plisio import PaymentProviderNotConfiguredError, PlisioError, list_currencies
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

logger = logging.getLogger(__name__)

_MANAGE_PLANS_CATEGORY_ORDER = ("trial", "scroll", "stream", "trip")
_MAX_PLAN_PRICE = Decimal("1000")
_INVALID_PRICE_TEXT = "⚠️ Send a valid price — a positive number under $1000 (e.g. 12.50)."
_ZERO_PRICE_ACTIVATION_TEXT = "⚠️ Set a price above $0.00 before activating."
_LOST_PLAN_CONTEXT_TEXT = "⚠️ Something went wrong — please start again."


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
    if not raw.isdigit():
        await message.answer(_INVALID_DAYS_TEXT, reply_markup=settings_edit_cancel_keyboard())
        return
    try:
        days = int(raw)
    except ValueError:
        await message.answer(_INVALID_DAYS_TEXT, reply_markup=settings_edit_cancel_keyboard())
        return
    if not (1 <= days <= 365):
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


async def _trial_limit_status_text(session: AsyncSession) -> str:
    enabled = (await get_config(session, "trial_limit_enabled")) != "false"
    state_line = "🟢 Enabled" if enabled else "🔴 Disabled"
    return (
        "🎁 <b>Trial Limit</b>\n\n"
        "When enabled, each customer can claim only one free trial, ever. "
        "Turning it off lets everyone (including customers who already "
        "claimed one) start another trial.\n\n"
        f"State: {state_line}"
    )


def _trial_limit_settings_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴 Turn Off" if enabled else "🟢 Turn On", callback_data="adm:settings:trial:toggle")
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "adm:settings:trial")
async def settings_trial_limit_status_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        enabled = (await get_config(session, "trial_limit_enabled")) != "false"
        text = await _trial_limit_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_trial_limit_settings_keyboard(enabled=enabled))
    await callback.answer()


@router.callback_query(F.data == "adm:settings:trial:toggle")
async def settings_toggle_trial_limit_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        currently_enabled = (await get_config(session, "trial_limit_enabled")) != "false"
        await set_config(session, "trial_limit_enabled", "false" if currently_enabled else "true")
        enabled = not currently_enabled
        text = await _trial_limit_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_trial_limit_settings_keyboard(enabled=enabled))
    await callback.answer()


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
            f"Current price for {html.escape(plan.name)} ({html.escape(plan.category)}): "
            f"{format_price_usd(plan.price_usd)}\n\n"
            "Send the new price (e.g. 12.50):",
            reply_markup=manage_plans_price_edit_cancel_keyboard(plan_id),
        )
    await callback.answer()


@router.message(EditPlanPriceStates.price)
async def manage_plan_receive_price(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    # FSM data can legitimately be missing here (storage restart, a state
    # entered by some path that never set plan_id) - degrade to a generic
    # restart prompt instead of raising KeyError out of the handler.
    plan_id = data.get("plan_id")
    if plan_id is None:
        await state.clear()
        await message.answer(_LOST_PLAN_CONTEXT_TEXT, reply_markup=back_to_settings_keyboard())
        return
    raw = (message.text or "").strip()

    try:
        new_price = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        await message.answer(_INVALID_PRICE_TEXT, reply_markup=manage_plans_price_edit_cancel_keyboard(plan_id))
        return
    if not new_price.is_finite() or new_price <= 0 or new_price >= _MAX_PLAN_PRICE:
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
        "admin_price_change admin=%s plan=%s old_price=%s new_price=%s timestamp=%s",
        message.from_user.id if message.from_user is not None else None,
        plan_id,
        old_price,
        new_price,
        dt.datetime.now(dt.timezone.utc).isoformat(),
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
        # Price floor: a plan must never go live at the $0.00 placeholder
        # the catalog migration inserts (or at a price an admin zeroed
        # out). Trial is exempt - it's a legitimate permanent $0.00
        # product. Refuse BEFORE any write, so is_active is left untouched.
        if not plan.is_active and plan.category != "trial" and plan.price_usd <= 0:
            await callback.answer(_ZERO_PRICE_ACTIVATION_TEXT, show_alert=True)
            return
        updated = await update_plan(session, plan_id, is_active=not plan.is_active)

    if callback.message is not None and updated is not None:
        await callback.message.edit_text(plan_detail_text(updated), reply_markup=manage_plans_detail_keyboard(updated))
    await callback.answer()


_CRYPTO_INVALID_ADDRESS_TEXT = "⚠️ {reason}\n\nSend a valid {network} address:"


async def _crypto_settlement_status_text(session: AsyncSession) -> str:
    address = await get_config(session, "crypto_settlement_address")
    network = await get_config(session, "crypto_settlement_network")
    body = (
        "💳 <b>Crypto Settlement Address</b>\n\n"
        "Internal reference record only — never wired into Plisio, purely "
        "for the team to know where payouts are meant to land."
    )
    if address is None or network is None:
        return f"{body}\n\nNo settlement address configured yet."
    label = NETWORK_LABELS.get(network, html.escape(network))
    return f"{body}\n\nNetwork: {label}\nAddress: <code>{html.escape(address)}</code>"


@router.callback_query(F.data == "adm:settings:crypto")
async def crypto_settlement_status_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        text = await _crypto_settlement_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=crypto_settlement_status_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm:settings:crypto:edit")
async def crypto_settlement_edit_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text("Choose the network:", reply_markup=crypto_network_choice_keyboard())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^adm:settings:crypto:network:(.+)$"))
async def crypto_settlement_network_cb(callback: CallbackQuery, state: FSMContext) -> None:
    network = callback.data.split(":", 4)[-1]
    if network not in NETWORK_LABELS:
        if callback.message is not None:
            await callback.message.edit_text("⚠️ Unknown network.", reply_markup=crypto_network_choice_keyboard())
        await callback.answer()
        return
    await state.set_state(EditCryptoSettlementStates.address)
    await state.update_data(network=network)
    if callback.message is not None:
        await callback.message.edit_text(
            f"Send the {NETWORK_LABELS[network]} address:",
            reply_markup=crypto_settlement_edit_cancel_keyboard(),
        )
    await callback.answer()


@router.message(EditCryptoSettlementStates.address)
async def crypto_settlement_receive_address(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    network = data.get("network")
    if network not in NETWORK_LABELS:
        await state.clear()
        await message.answer("⚠️ Something went wrong — please start again.", reply_markup=back_to_settings_keyboard())
        return

    address = (message.text or "").strip()
    label = NETWORK_LABELS[network]
    if not address:
        await message.answer(
            _CRYPTO_INVALID_ADDRESS_TEXT.format(reason="Send a non-empty value.", network=label),
            reply_markup=crypto_settlement_edit_cancel_keyboard(),
        )
        return

    # No API-side validation: Plisio documents no address-validation
    # endpoint, and this record is an internal note about where payouts
    # are meant to land rather than anything wired into the gateway.
    # Payout wallets themselves are configured in the Plisio dashboard.

    async with async_session_maker() as session:
        await set_config(session, "crypto_settlement_address", address)
        await set_config(session, "crypto_settlement_network", network)
        text = await _crypto_settlement_status_text(session)
    await state.clear()
    await message.answer(f"✅ Settlement address saved.\n\n{text}", reply_markup=crypto_settlement_status_keyboard())


def _coin_line(row: dict[str, Any]) -> str:
    """One coin's live state. English-only, like every adm:* screen."""
    name = html.escape(str(row.get("name") or row.get("cid") or "?"))
    cid = html.escape(str(row.get("cid") or "?"))
    raw_min = str(row.get("min_sum_in") or "?")
    try:
        min_usd = f"${Decimal(str(row.get('min_sum_in') or 0)) * Decimal(str(row.get('price_usd') or 0)):.2f}"
    except (ArithmeticError, InvalidOperation, ValueError):
        min_usd = "unknown"

    flags = []
    if row.get("maintenance"):
        flags.append("maintenance")
    if str(row.get("hidden", "0")) not in ("0", "False", "false"):
        flags.append("not enabled on this account")
    suffix = f" — {', '.join(flags)}" if flags else ""
    return f"• <b>{name}</b> ({cid}): min {html.escape(raw_min)} ≈ {min_usd}{suffix}"


async def _crypto_coins_text() -> str:
    accepted = get_settings().plisio_pay_currency_list
    try:
        rows = await list_currencies()
    except PaymentProviderNotConfiguredError:
        return "💱 <b>Crypto Coins</b>\n\nPlisio isn't configured yet (PLISIO_SECRET_KEY is blank)."
    except PlisioError as exc:
        logger.error("Plisio currencies lookup failed", exc_info=True)
        return f"💱 <b>Crypto Coins</b>\n\n⚠️ Couldn't reach Plisio: {html.escape(str(exc)[:300])}"

    by_cid = {str(row.get("cid")): row for row in rows}
    lines = [
        _coin_line(by_cid[cid]) if cid in by_cid else f"• <b>{html.escape(cid)}</b>: not offered by Plisio"
        for cid in accepted
    ]
    return (
        "💱 <b>Crypto Coins</b>\n\n"
        "The coins buyers can choose on the Plisio invoice page, with Plisio's own "
        "live minimum per coin.\n\n" + ("\n".join(lines) or "No pay currencies configured.")
    )


@router.callback_query(F.data == "adm:settings:coins")
async def settings_crypto_coins_cb(callback: CallbackQuery, state: FSMContext) -> None:
    # No inline permission check: this whole router is gated by IsFullAdmin.
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(await _crypto_coins_text(), reply_markup=back_to_settings_keyboard())
    await callback.answer()
