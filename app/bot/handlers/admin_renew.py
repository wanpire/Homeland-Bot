from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards.admin_renew import (
    admin_renew_plan_keyboard,
    admin_renew_result_keyboard,
    admin_renew_username_prompt_keyboard,
)
from app.bot.states.admin_renew import AdminRenewStates
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.catalog import get_plan, list_plans
from app.services.groups import is_homeland_group
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserNotFoundError
from app.services.vpn_users import renew_and_change_group

router = Router(name="admin_renew")

logger = logging.getLogger(__name__)

_USERNAME_PROMPT_TEXT = "Send the IBSng username to renew:"
_EMPTY_USERNAME_TEXT = "⚠️ Send a non-empty username."
_VERIFY_FAILED_TEXT = "⚠️ Couldn't verify this account right now — please try again shortly."
_PLAN_PROMPT_TEXT = "Pick the plan/group to renew into:"
_PLAN_GONE_TEXT = "⚠️ That plan no longer exists. Start over."


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


@router.callback_query(F.data == "adm:users:renew")
async def admin_renew_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminRenewStates.username)
    if callback.message is not None:
        await callback.message.edit_text(_USERNAME_PROMPT_TEXT, reply_markup=admin_renew_username_prompt_keyboard())
    await callback.answer()


@router.message(AdminRenewStates.username)
async def admin_renew_receive_username(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    username = (message.text or "").strip()
    if not username:
        await message.answer(_EMPTY_USERNAME_TEXT, reply_markup=admin_renew_username_prompt_keyboard())
        return

    # Namespace guard, BEFORE the plan picker is ever offered. This flow
    # is the branch's only write path into an arbitrary typed IBSng
    # username, and the IBSng instance is shared with AloBot (see
    # CLAUDE.md and app/services/groups.py): renewing a mistyped or
    # pasted AloBot username would reset another business's customer
    # account and move it into a Homeland pricing group. Refuse before
    # anything is mutated rather than relying on the execute step.
    try:
        async with IBSngClient() as client:
            current_group = await client.get_user_group(username=username)
    except IBSngError:
        logger.exception("Could not verify IBSng group for username=%r", username)
        await message.answer(_VERIFY_FAILED_TEXT, reply_markup=admin_renew_username_prompt_keyboard())
        return

    if current_group is None:
        await message.answer(
            f"⚠️ IBSng user {username!r} not found.", reply_markup=admin_renew_username_prompt_keyboard()
        )
        return
    if not is_homeland_group(current_group):
        await message.answer(
            f"⚠️ {username!r} isn't a Homeland account (currently in group "
            f"{current_group!r}) — refusing to modify it.",
            reply_markup=admin_renew_username_prompt_keyboard(),
        )
        return

    await state.update_data(username=username)
    await state.set_state(AdminRenewStates.plan)
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    await message.answer(_PLAN_PROMPT_TEXT, reply_markup=admin_renew_plan_keyboard(plans))


@router.callback_query(AdminRenewStates.plan, F.data.startswith("adm:users:renew:plan:"))
async def admin_renew_execute_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    plan_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    username = data["username"]
    await state.clear()

    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
    if plan is None:
        if callback.message is not None:
            await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=admin_renew_result_keyboard())
        await callback.answer()
        return

    try:
        async with async_session_maker() as session, IBSngClient() as client:
            await renew_and_change_group(
                session, client, username=username, new_group_name=plan.group_name,
                new_plan_id=plan.id, new_data_cap_mb=plan.data_cap_mb,
            )
    except IBSngUserNotFoundError:
        if callback.message is not None:
            await callback.message.edit_text(
                f"⚠️ IBSng user {username!r} not found.", reply_markup=admin_renew_result_keyboard()
            )
        await callback.answer()
        return
    except IBSngError as exc:
        if callback.message is not None:
            await callback.message.edit_text(f"⚠️ {exc}", reply_markup=admin_renew_result_keyboard())
        await callback.answer()
        return

    async with async_session_maker() as session:
        vpn_user = (
            await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))
        ).scalar_one_or_none()

    result_text = f"✅ Renewed {username!r} and moved to {plan.name}."
    if vpn_user is None:
        result_text += "\n\n(No local account record — this username wasn't created through the bot.)"
    else:
        try:
            await callback.bot.send_message(
                vpn_user.telegram_id,
                f"✅ Your Homeland VPN service was renewed by support — now on {plan.name}.",
            )
        except TelegramAPIError:
            logger.exception("Could not notify telegram_id=%s about their renewal", vpn_user.telegram_id)

    if callback.message is not None:
        await callback.message.edit_text(result_text, reply_markup=admin_renew_result_keyboard())
    await callback.answer()
