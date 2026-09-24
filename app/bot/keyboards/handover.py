"""The two pickers of the shared handover sequence (app/services/handover.py).

Callback data carries the source and its row id (`ho:<src>:<ref>:…`), so
every step is stateless and a picker left in chat history still works.
Platform and protocol labels are proper nouns and stay untranslated."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.i18n.texts import t


def handover_prefix(source: str, ref: int) -> str:
    return f"ho:{source}:{ref}"


def handover_platform_keyboard(
    source: str, ref: int, platforms: list[TutorialPlatform], lang: str, *, back_callback: str | None
) -> InlineKeyboardMarkup:
    """Step 1. `back_callback` is None for a paid order: its prompt is a
    message the bot sent, and a main-menu tap would edit away the only
    route to the credentials."""
    prefix = handover_prefix(source, ref)
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"{prefix}:os:{platform.id}")
    if back_callback is not None:
        builder.button(text=t("back_to_menu", lang), callback_data=back_callback)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def handover_protocol_keyboard(
    source: str, ref: int, platform_id: int, protocols: list[TutorialProtocol], lang: str
) -> InlineKeyboardMarkup:
    """Step 2, listing only the protocols the chosen device supports."""
    prefix = handover_prefix(source, ref)
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"{prefix}:pr:{platform_id}:{protocol.id}")
    builder.button(text=t("back_button", lang), callback_data=f"{prefix}:back")
    builder.adjust(2, 1)
    return builder.as_markup()
