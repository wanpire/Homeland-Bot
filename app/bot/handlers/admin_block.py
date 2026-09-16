from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.bot.keyboards.admin_block import PAGE_SIZE, block_user_prompt_keyboard, blocked_users_keyboard
from app.bot.states.admin_block import BlockUserStates
from app.db.models.bot_user import BotUser
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.bot_users import block_user, list_blocked_users

router = Router(name="admin_block")

_BLOCKED_LIST_TEXT = "🚫 <b>Blocked Users</b>"
_BLOCK_PROMPT_TEXT = "Send the numeric Telegram ID to block:"
_NOT_A_NUMBER_TEXT = "⚠️ Send a numeric Telegram ID."
_NEVER_SEEN_TEXT = "⚠️ That Telegram ID has never interacted with the bot — nothing to block."


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


async def _render_page(page: int) -> tuple[str, InlineKeyboardMarkup]:
    async with async_session_maker() as session:
        blocked = await list_blocked_users(session)
    total = len(blocked)
    start = page * PAGE_SIZE
    page_items = blocked[start : start + PAGE_SIZE]
    text = _BLOCKED_LIST_TEXT if page_items else f"{_BLOCKED_LIST_TEXT}\n\nNo blocked users."
    return text, blocked_users_keyboard(page_items, page=page, total=total)


@router.callback_query(F.data.startswith("adm:users:blocked:"))
async def admin_blocked_list_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    page = int(callback.data.split(":")[-1])
    text, keyboard = await _render_page(page)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:users:unblock:"))
async def admin_unblock_cb(callback: CallbackQuery) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, _, telegram_id_str, page_str = callback.data.split(":")
    async with async_session_maker() as session:
        await block_user(session, int(telegram_id_str), blocked=False)
    text, keyboard = await _render_page(int(page_str))
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("✅ Unblocked.")


@router.callback_query(F.data == "adm:users:block")
async def admin_block_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BlockUserStates.telegram_id)
    if callback.message is not None:
        await callback.message.edit_text(_BLOCK_PROMPT_TEXT, reply_markup=block_user_prompt_keyboard())
    await callback.answer()


@router.message(BlockUserStates.telegram_id)
async def admin_block_receive_id(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(_NOT_A_NUMBER_TEXT, reply_markup=block_user_prompt_keyboard())
        return
    telegram_id = int(raw)

    async with async_session_maker() as session:
        row = (await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))).scalar_one_or_none()
        if row is None:
            await message.answer(_NEVER_SEEN_TEXT, reply_markup=block_user_prompt_keyboard())
            return
        await block_user(session, telegram_id, blocked=True)

    await state.clear()
    text, keyboard = await _render_page(0)
    await message.answer(f"✅ Blocked {telegram_id}.\n\n{text}", reply_markup=keyboard)
