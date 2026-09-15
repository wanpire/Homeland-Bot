from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol


def tutorial_admin_root_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Upload a guide", callback_data="tutadm:guide")
    builder.button(text="📡 Upload an OpenVPN profile", callback_data="tutadm:profile")
    builder.button(text="📥 Set a download link", callback_data="tutadm:link")
    builder.adjust(1)
    return builder.as_markup()


def admin_protocol_keyboard(protocols: list[TutorialProtocol], *, target: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"tutadm:{target}:protocol:{protocol.id}")
    builder.adjust(2)
    return builder.as_markup()


def admin_platform_keyboard(platforms: list[TutorialPlatform], *, target: str, allow_generic: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"tutadm:{target}:platform:{platform.id}")
    if allow_generic:
        builder.button(text="Generic (any platform)", callback_data=f"tutadm:{target}:platform:none")
    builder.adjust(2)
    return builder.as_markup()
