from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol

# Back-navigation callbacks, one per step of the admin flow. Each sends
# the admin to the PREVIOUS screen of this flow (the root menu's Back
# leaves the flow entirely, for the main menu), matching the trial
# flow's own back-one-step convention.
BACK_TO_ROOT_CB = "tutadm:back:root"
BACK_TO_PROTOCOL_CB = "tutadm:back:protocol"
BACK_TO_PLATFORM_CB = "tutadm:back:platform"


def tutorial_admin_root_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Upload a guide", callback_data="tutadm:guide")
    builder.button(text="📡 Upload an OpenVPN profile", callback_data="tutadm:profile")
    builder.button(text="📥 Set a download link", callback_data="tutadm:link")
    # There is no admin root menu yet (the full Admin Panel is its own
    # later project), so this flow's own root steps back to the bot's
    # main menu rather than nowhere.
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def admin_protocol_keyboard(protocols: list[TutorialProtocol], *, target: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"tutadm:{target}:protocol:{protocol.id}")
    builder.button(text="⬅️ Back", callback_data=BACK_TO_ROOT_CB)
    builder.adjust(2, 1)
    return builder.as_markup()


def admin_platform_keyboard(platforms: list[TutorialPlatform], *, target: str, allow_generic: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"tutadm:{target}:platform:{platform.id}")
    if allow_generic:
        builder.button(text="Generic (any platform)", callback_data=f"tutadm:{target}:platform:none")
    builder.button(text="⬅️ Back", callback_data=BACK_TO_PROTOCOL_CB)
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def admin_content_prompt_keyboard() -> InlineKeyboardMarkup:
    """The "now send me the content" step is a screen the admin can
    otherwise only leave by sending something, so it gets a Back button
    too - same convention as every other screen in the flow."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data=BACK_TO_PLATFORM_CB)
    builder.adjust(1)
    return builder.as_markup()
