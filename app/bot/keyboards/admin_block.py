from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.bot_user import BotUser

PAGE_SIZE = 8


def blocked_users_keyboard(page_items: list[BotUser], *, page: int, total: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in page_items:
        label = f"@{user.username}" if user.username else str(user.telegram_id)
        builder.button(text=f"✅ Unblock {label}", callback_data=f"adm:users:unblock:{user.telegram_id}:{page}")
    sizes = [1] * len(page_items)

    nav_count = 0
    if page > 0:
        builder.button(text="◀️ Prev", callback_data=f"adm:users:blocked:{page - 1}")
        nav_count += 1
    if (page + 1) * PAGE_SIZE < total:
        builder.button(text="Next ▶️", callback_data=f"adm:users:blocked:{page + 1}")
        nav_count += 1
    if nav_count:
        sizes.append(nav_count)

    builder.button(text="🚫 Block a User", callback_data="adm:users:block")
    builder.button(text="⬅️ Back to Users", callback_data="adm:users")
    sizes += [1, 1]
    builder.adjust(*sizes)
    return builder.as_markup()


def block_user_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:users:blocked:0")
    builder.adjust(1)
    return builder.as_markup()
