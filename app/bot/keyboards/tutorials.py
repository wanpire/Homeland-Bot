"""Keyboards for the customer-facing Tutorials section (menu:tutorials).

Separate from trial.py's and myservices.py's protocol/platform keyboards
even though the lists are the same: those carry their own flow's callback
data (a trial in progress, a specific service id), while these are
standalone and must return the user to the main menu rather than into
someone else's flow."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.i18n.texts import t


def tutorials_protocol_keyboard(protocols: list[TutorialProtocol], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"tut:protocol:{protocol.id}")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def tutorials_platform_keyboard(platforms: list[TutorialPlatform], protocol_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"tut:platform:{protocol_id}:{platform.id}")
    builder.button(text=t("back_button", lang), callback_data="menu:tutorials")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def tutorials_done_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Sent after a delivery so the section never dead-ends: the guide
    arrives as fresh messages, leaving the last screen's own keyboard
    scrolled far above."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("tutorials_another_button", lang), callback_data="menu:tutorials")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
