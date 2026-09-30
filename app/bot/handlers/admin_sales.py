"""Financial → Sales Status: the switch that pauses every new sale
(purchase, renewal, trial) and the message customers see meanwhile.

Full admins only, English only. The switch lives in
app/services/sales_status.py; the customer-side check is
app/bot/sales_gate.py."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin import back_to_financial_keyboard
from app.bot.keyboards.admin_sales import sales_message_cancel_keyboard, sales_status_keyboard
from app.bot.states.admin_sales import EditSalesMessageStates
from app.db.session import async_session_maker
from app.services.adminlog import SALES_STATUS, log_event
from app.services.sales_status import (
    MAX_PAUSED_MESSAGE_LENGTH,
    MESSAGE_LANGUAGES,
    are_sales_enabled,
    clear_custom_paused_messages,
    default_paused_message,
    get_custom_paused_message,
    set_custom_paused_message,
    set_sales_enabled,
)

router = Router(name="admin_sales")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

_PREVIEW_LIMIT = 200
_LANG_NAMES = {"fa": "Persian", "en": "English"}
_LANG_FLAGS = {"fa": "🇮🇷 FA", "en": "🇬🇧 EN"}
_EMPTY_TEXT = "⚠️ Send a non-empty message, or cancel."
_NOT_TEXT_TEXT = "⚠️ Send the message as plain text, or cancel."
_TOO_LONG_TEXT = f"⚠️ That is too long — keep it under {MAX_PAUSED_MESSAGE_LENGTH} characters, or cancel."
_LOST_CONTEXT_TEXT = "⚠️ Something went wrong — please start again."


async def _preview(session: AsyncSession, lang: str) -> str:
    custom = await get_custom_paused_message(session, lang)
    if custom is None:
        # The default is short, fixed and already valid HTML: shown whole.
        return f"{_LANG_FLAGS[lang]} (default):\n{default_paused_message(lang)}"
    clipped = custom if len(custom) <= _PREVIEW_LIMIT else f"{custom[:_PREVIEW_LIMIT]}…"
    return f"{_LANG_FLAGS[lang]} (custom):\n{html.escape(clipped)}"


async def _status(session: AsyncSession) -> tuple[str, bool]:
    enabled = await are_sales_enabled(session)
    state_line = "🟢 Sales enabled" if enabled else "🔴 Sales disabled"
    lines = [
        "🛑 <b>Sales Status</b>",
        "",
        f"State: {state_line}",
        "",
        "Message shown to customers while disabled:",
        "",
        await _preview(session, "fa"),
        "",
        await _preview(session, "en"),
    ]
    return "\n".join(lines), enabled


def _who(user: User) -> str:
    return f"@{user.username} ({user.id})" if user.username else str(user.id)


async def _render(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        text, enabled = await _status(session)
    if callback.message is not None:
        try:
            await callback.message.edit_text(text, reply_markup=sales_status_keyboard(enabled=enabled))
        except TelegramBadRequest as exc:
            # Nothing changed on screen (Reset while already default, two
            # racing taps): Telegram refuses the identical edit. Harmless.
            if "not modified" not in str(exc).lower():
                raise


@router.callback_query(F.data == "adm:fin:sales")
async def sales_status_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _render(callback)
    await callback.answer()


@router.callback_query(F.data.in_({"adm:fin:sales:set:off", "adm:fin:sales:set:on"}))
async def sales_set_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    enable = callback.data.endswith(":on")
    async with async_session_maker() as session:
        changed = await are_sales_enabled(session) != enable
        if changed:
            await set_sales_enabled(session, enable)
    if changed:
        await log_event(
            callback.bot, SALES_STATUS,
            State="🟢 ENABLED" if enable else "🔴 DISABLED", Admin=_who(callback.from_user),
        )
    await _render(callback)
    await callback.answer()


@router.callback_query(F.data.in_({"adm:fin:sales:msg:fa", "adm:fin:sales:msg:en"}))
async def sales_message_prompt_cb(callback: CallbackQuery, state: FSMContext) -> None:
    lang = callback.data.rsplit(":", 1)[-1]
    await state.set_state(EditSalesMessageStates.text)
    await state.update_data(lang=lang)
    if callback.message is not None:
        await callback.message.edit_text(
            f"✏️ Send the <b>{_LANG_NAMES[lang]}</b> message customers will see while sales are "
            f"disabled. Plain text, up to {MAX_PAUSED_MESSAGE_LENGTH} characters.",
            reply_markup=sales_message_cancel_keyboard(),
        )
    await callback.answer()


@router.message(EditSalesMessageStates.text)
async def sales_message_receive(message: Message, state: FSMContext) -> None:
    lang = (await state.get_data()).get("lang")
    if lang not in MESSAGE_LANGUAGES:
        await state.clear()
        await message.answer(_LOST_CONTEXT_TEXT, reply_markup=back_to_financial_keyboard())
        return

    if message.text is None:
        await message.answer(_NOT_TEXT_TEXT, reply_markup=sales_message_cancel_keyboard())
        return
    value = message.text.strip()
    if not value:
        await message.answer(_EMPTY_TEXT, reply_markup=sales_message_cancel_keyboard())
        return
    # Telegram's limit counts UTF-16 code units, not code points.
    if len(value.encode("utf-16-le")) // 2 > MAX_PAUSED_MESSAGE_LENGTH:
        await message.answer(_TOO_LONG_TEXT, reply_markup=sales_message_cancel_keyboard())
        return

    async with async_session_maker() as session:
        await set_custom_paused_message(session, lang, value)
        text, enabled = await _status(session)
    await state.clear()
    await message.answer(
        f"✅ {_LANG_NAMES[lang]} message saved.\n\n{text}", reply_markup=sales_status_keyboard(enabled=enabled)
    )


@router.callback_query(F.data == "adm:fin:sales:reset")
async def sales_message_reset_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        await clear_custom_paused_messages(session)
    await _render(callback)
    await callback.answer("Messages reset to default.")
