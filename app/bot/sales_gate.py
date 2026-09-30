"""The ONE customer-side check of the sales switch.

Called first thing in exactly six handlers - buy:plan, buy:confirm,
renew:plan, renew:confirm, menu:trial, trial:confirm - so a customer can
browse the menus but is stopped the moment they pick something. The
confirm handlers re-check because an old button in chat history can
reach them without passing the first step. Never gate payment
confirmation: an invoice that is already paid is always honored."""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.sales_gate import sales_paused_keyboard
from app.db.session import async_session_maker
from app.services.sales_status import are_sales_enabled, sales_paused_text


async def block_if_sales_paused(callback: CallbackQuery, lang: str) -> bool:
    """True when sales are paused - the paused screen is already shown
    and the callback answered, so the caller just returns."""
    async with async_session_maker() as session:
        if await are_sales_enabled(session):
            return False
        text = await sales_paused_text(session, lang)
    if callback.message is not None:
        # show_screen, not edit_text: menu:trial can arrive from an Ad
        # Campaign photo, which cannot be edited into a text screen.
        try:
            await show_screen(callback.message, text, sales_paused_keyboard(lang))
        except TelegramBadRequest as exc:
            # A double tap re-renders the identical paused screen, which
            # Telegram refuses as "not modified". Harmless: still answer.
            if "not modified" not in str(exc).lower():
                raise
    await callback.answer()
    return True
