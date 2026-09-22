"""Find one customer and see everything about them on a single screen.

Search parsing is imported from app/services/reporting.py rather than
rewritten, so Financial's payment search and this one can never disagree
about what "@someone" means."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.admin_renew import admin_renew_plan_keyboard, admin_renew_username_prompt_keyboard
from app.bot.keyboards.user_admin import user_detail_keyboard, user_search_prompt_keyboard
from app.bot.states.admin_renew import AdminRenewStates
from app.bot.states.user_admin import UserLookupStates
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.catalog import list_plans
from app.services.bot_users import block_user
from app.services.groups import is_homeland_group
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.reporting import resolve_user_query
from app.services.user_admin import UserOverview, user_overview

logger = logging.getLogger(__name__)

router = Router(name="user_admin")

_SEARCH_PROMPT = (
    "🔍 <b>Find a user</b>\n\nSend a Telegram ID or a @username."
)
_NO_MATCH = "⚠️ No user matches that. Send a Telegram ID or a @username, or cancel."
_NOT_A_USER = "⚠️ That ID has never used the bot."
_VERIFY_FAILED = "⚠️ Couldn't verify this account with IBSng right now — please try again shortly."


async def _is_support(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


def _detail_text(overview: UserOverview) -> str:
    lines = [
        f"👤 <b>{html.escape(overview.display_name)}</b>",
        f"Telegram ID: <code>{overview.telegram_id}</code>",
    ]
    if overview.first_seen_at is not None:
        lines.append(f"First seen: {overview.first_seen_at:%Y-%m-%d}")
    lines.append(f"Language: {overview.language or 'not set'}")
    lines.append("Status: 🚫 blocked" if overview.is_blocked else "Status: active")
    lines.append(f"Trial: {'used' if overview.trial_used else 'not used'}")

    lines.append("")
    if overview.services:
        lines.append(f"<b>Services ({overview.total_services})</b>")
        for service in overview.services:
            when = f" until {service.expires_at:%Y-%m-%d}" if service.expires_at is not None else ""
            label = "Trial" if service.is_trial else html.escape(service.plan_name)
            lines.append(f"• <code>{html.escape(service.ibsng_username)}</code> — {label} · {service.status}{when}")
        if overview.truncated_services:
            lines.append(f"…and {overview.truncated_services} older service(s)")
    else:
        lines.append("<b>Services</b>\nNone yet.")

    payments = overview.payments
    lines += ["", "<b>Payments</b>"]
    last = f" · last {payments.last_paid_at:%d %b}" if payments.last_paid_at is not None else ""
    lines.append(f"Paid: {payments.paid} · ${payments.total_paid_usd} total{last}")
    lines.append(f"Pending: {payments.pending} · Failed: {payments.failed}")
    return "\n".join(lines)


async def _render_detail(message: Message, telegram_id: int, viewer_id: int) -> None:
    async with async_session_maker() as session, IBSngClient() as client:
        overview = await user_overview(session, client, telegram_id)
    if overview is None:
        await message.answer(_NOT_A_USER, reply_markup=user_search_prompt_keyboard())
        return

    async with async_session_maker() as session:
        can_see_payments = await has_level(session, viewer_id, "sales")

    await message.answer(
        _detail_text(overview),
        reply_markup=user_detail_keyboard(overview, can_see_payments=can_see_payments),
    )


@router.callback_query(F.data == "adm:users:find")
async def user_find_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_support(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(UserLookupStates.query)
    if callback.message is not None:
        await callback.message.edit_text(_SEARCH_PROMPT, reply_markup=user_search_prompt_keyboard())
    await callback.answer()


@router.message(UserLookupStates.query)
async def user_find_msg(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_support(message.from_user.id):
        await state.clear()
        return

    async with async_session_maker() as session:
        telegram_id = await resolve_user_query(session, message.text or "")

    if telegram_id is None:
        # Never fall back to a list: that would quietly answer a
        # different question than the one asked.
        await message.answer(_NO_MATCH, reply_markup=user_search_prompt_keyboard())
        return

    await state.clear()
    await _render_detail(message, telegram_id, message.from_user.id)


@router.callback_query(F.data.startswith("adm:users:view:"))
async def user_view_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_support(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    try:
        telegram_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    if callback.message is not None:
        await _render_detail(callback.message, telegram_id, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:users:toggleblock:"))
async def user_toggle_block_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_support(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    try:
        telegram_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    async with async_session_maker() as session, IBSngClient() as client:
        overview = await user_overview(session, client, telegram_id)
    if overview is None:
        await callback.answer(_NOT_A_USER, show_alert=True)
        return

    async with async_session_maker() as session:
        await block_user(session, telegram_id, not overview.is_blocked)

    if callback.message is not None:
        await _render_detail(callback.message, telegram_id, callback.from_user.id)
    await callback.answer("Blocked." if not overview.is_blocked else "Unblocked.")


@router.callback_query(F.data.startswith("adm:users:renewsvc:"))
async def user_renew_service_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Jumps into the existing renew flow with the username filled in.

    The Homeland-group guard is re-run rather than trusted: this IBSng
    instance is shared with AloBot, and an account moved out of a
    Homeland group since purchase is exactly what the guard exists to
    catch."""
    if not await _is_support(callback.from_user.id):
        await callback.answer()
        return
    try:
        vpn_user_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    async with async_session_maker() as session:
        vpn_user = await session.get(VPNUser, vpn_user_id)
    if vpn_user is None:
        await callback.answer("⚠️ That service no longer exists.", show_alert=True)
        return

    try:
        async with IBSngClient() as client:
            current_group = await client.get_user_group(username=vpn_user.ibsng_username)
    except IBSngError:
        logger.exception("Could not verify IBSng group for %r", vpn_user.ibsng_username)
        if callback.message is not None:
            await callback.message.answer(_VERIFY_FAILED, reply_markup=admin_renew_username_prompt_keyboard())
        await callback.answer()
        return

    if current_group is None or not is_homeland_group(current_group):
        await callback.answer(
            f"⚠️ {vpn_user.ibsng_username} isn't in a Homeland group — refusing to modify it.",
            show_alert=True,
        )
        return

    await state.set_state(AdminRenewStates.plan)
    await state.update_data(username=vpn_user.ibsng_username)
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    if callback.message is not None:
        await callback.message.answer(
            f"Renewing <code>{html.escape(vpn_user.ibsng_username)}</code> — pick the plan/group:",
            reply_markup=admin_renew_plan_keyboard(plans),
        )
    await callback.answer()
