from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.bot.keyboards.language import language_choice_keyboard
from app.db.session import async_session_maker
from app.i18n.texts import CHOOSE_LANGUAGE_TEXT
from app.services.bot_users import get_language


class LanguageMiddleware(BaseMiddleware):
    """Gates every update behind a one-time language choice, then attaches
    the resolved language to `data["lang"]` for every handler downstream -
    same interception shape as MandatoryChannelMiddleware, so a customer
    can never reach a handler with data["lang"] unset."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        inner: Message | CallbackQuery | None = event.message or event.callback_query
        if inner is None or inner.from_user is None:
            return await handler(event, data)

        # menu:language and lang:set:* must reach their own handlers even
        # with lang still unset - respectively re-running and answering
        # the chooser itself. Neither handler declares a `lang` parameter
        # (menu_language_cb's CHOOSE_LANGUAGE_TEXT is fixed/bilingual;
        # lang_set_cb parses the target language straight out of its own
        # callback_data), so there is nothing to attach to `data` here.
        callback_data = inner.data if isinstance(inner, CallbackQuery) else None
        if callback_data == "menu:language" or (callback_data or "").startswith("lang:set:"):
            return await handler(event, data)

        async with async_session_maker() as session:
            lang = await get_language(session, inner.from_user.id)

        if lang is None:
            if isinstance(inner, CallbackQuery):
                if inner.message is not None:
                    await inner.message.edit_text(CHOOSE_LANGUAGE_TEXT, reply_markup=language_choice_keyboard())
                await inner.answer()
            else:
                await inner.answer(CHOOSE_LANGUAGE_TEXT, reply_markup=language_choice_keyboard())
            return None

        data["lang"] = lang
        return await handler(event, data)
