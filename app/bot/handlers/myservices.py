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
_NOT_FOUND_TEXT = "⚠️ Service not found."


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
