"""Button-builder functions for the main menu and shared back controls.
Pure keyboard builders only - no handler logic here."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t


#: Languages whose menus are laid out right-to-left, so the pair in each
#: two-button row is swapped: the first item belongs under the reader's
#: eye, which in Persian is the right-hand column, not the left.
_RTL_LANGS = frozenset({"fa"})


def main_menu(*, is_admin: bool, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str, str | None]]] = [
        [
            (t("menu_buy", lang), "menu:buy", "success"),
            (t("menu_renew", lang), "menu:renew", "success"),
        ],
        [
            (t("menu_trial", lang), "menu:trial", "primary"),
            (t("menu_myservices", lang), "menu:myservices", "primary"),
        ],
        [
            (t("menu_tutorials", lang), "menu:tutorials", "danger"),
            (t("menu_support", lang), "menu:support", "danger"),
        ],
        [(t("menu_language", lang), "menu:language", None)],
    ]
    if is_admin:
        # Admin-facing, so English-only by project convention.
        rows.append([("🛠 Admin Panel", "adm:root", None)])

    builder = InlineKeyboardBuilder()
    sizes: list[int] = []
    for row in rows:
        # Telegram lays a row out left-to-right whatever the text, so an
        # RTL menu has to be reversed here for the reading order to come
        # out right. Single-button rows are unaffected.
        for text, callback_data, style in (list(reversed(row)) if lang in _RTL_LANGS else row):
            if style is None:
                builder.button(text=text, callback_data=callback_data)
            else:
                builder.button(text=text, callback_data=callback_data, style=style)
        sizes.append(len(row))

    builder.adjust(*sizes)
    return builder.as_markup()


def support_keyboard(url: str | None, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if url:
        builder.button(text=t("contact_support_button", lang), url=url)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


async def show_screen(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None) -> None:
    """Render a menu screen on the message the user tapped. A text
    message is edited in place (the usual case); a message with no text -
    an Ad Campaign photo whose button reuses main-menu callback data -
    can't be edited into a text screen (Telegram: "there is no text in
    the message to edit"), so a fresh message is sent instead. Every
    deeper screen in the flow then runs on that fresh text message and
    can keep using edit_text."""
    if message.text is None:
        await message.answer(text, reply_markup=reply_markup)
    else:
        await message.edit_text(text, reply_markup=reply_markup)
