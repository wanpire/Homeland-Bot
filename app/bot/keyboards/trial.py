from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol


def trial_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm", callback_data="trial:confirm", style="success")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def trial_protocol_keyboard(protocols: list[TutorialProtocol]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"trial:protocol:{protocol.id}")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def trial_platform_keyboard(platforms: list[TutorialPlatform]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"trial:platform:{platform.id}")
    builder.button(text="⬅️ Back", callback_data="trial:back_to_protocol")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
