"""The platform picker sent after an account handover.

Platform labels come from the catalog (iOS, Android, Windows, macOS) and
are proper nouns, so they are not translated; every other string here
goes through t()."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.i18n.texts import t


def openvpn_platform_keyboard(platforms: list[TutorialPlatform], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"ovpn:link:{platform.id}")
    # Anyone wanting the full walkthrough rather than just the app goes to
    # Tutorials, which owns the guides.
    builder.button(text=t("tutorial_button", lang), callback_data="menu:tutorials")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
