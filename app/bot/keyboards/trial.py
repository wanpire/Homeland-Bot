from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.i18n.texts import t


def trial_confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("confirm_button", lang), callback_data="trial:confirm", style="success")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def trial_protocol_keyboard(protocols: list[TutorialProtocol], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"trial:protocol:{protocol.id}")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def trial_os_keyboard(protocol_id: int, platforms: list[TutorialPlatform], lang: str) -> InlineKeyboardMarkup:
    """The device step, asked for every protocol before anything is sent.
    The protocol travels in the callback so the next step needs no FSM."""
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"trial:os:{protocol_id}:{platform.id}")
    builder.button(text=t("back_button", lang), callback_data="trial:back_to_protocol")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
