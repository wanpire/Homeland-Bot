"""The ONE sales switch: whether new purchases, renewals and trial
activations are allowed, and what a customer is told while they are not.

Stored in app_config like every other admin toggle. The flag is named for
the normal state - `sales_enabled` - and an absent row means enabled, so
deploying this changes nothing until an admin flips it. The customer-side
check is app/bot/sales_gate.py; the admin screen is
app/bot/handlers/admin_sales.py.

Paying an invoice that already exists is deliberately NOT gated by this:
the customer has paid, so app/services/payments/confirmation.py never
reads it."""

from __future__ import annotations

import html

from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n.texts import t
from app.services.app_config import get_config, set_config

_ENABLED_KEY = "sales_enabled"
_MESSAGE_KEYS: dict[str, str] = {"fa": "sales_paused_message_fa", "en": "sales_paused_message_en"}

MESSAGE_LANGUAGES: tuple[str, ...] = ("fa", "en")
#: Leaves headroom under Telegram's 4096 limit, which (like this one) is
#: measured in UTF-16 code units, not Python code points.
MAX_PAUSED_MESSAGE_LENGTH = 3500


def _message_key(lang: str) -> str:
    return _MESSAGE_KEYS.get(lang, _MESSAGE_KEYS["en"])


async def are_sales_enabled(session: AsyncSession) -> bool:
    return (await get_config(session, _ENABLED_KEY)) != "false"


async def set_sales_enabled(session: AsyncSession, enabled: bool) -> None:
    await set_config(session, _ENABLED_KEY, "true" if enabled else "false")


async def get_custom_paused_message(session: AsyncSession, lang: str) -> str | None:
    """The admin's text for `lang`, or None when unset (an empty value
    counts as unset - that is how clearing works)."""
    raw = await get_config(session, _message_key(lang))
    return raw if raw and raw.strip() else None


async def set_custom_paused_message(session: AsyncSession, lang: str, text: str) -> None:
    if lang not in _MESSAGE_KEYS:
        raise ValueError(f"unsupported language for the paused message: {lang!r}")
    await set_config(session, _MESSAGE_KEYS[lang], text)


async def clear_custom_paused_messages(session: AsyncSession) -> None:
    for key in _MESSAGE_KEYS.values():
        await set_config(session, key, "")


def default_paused_message(lang: str) -> str:
    return t("sales_paused_default", lang)


async def sales_paused_text(session: AsyncSession, lang: str) -> str:
    """What the customer sees. Custom text is plain text, so it is
    escaped: an admin typing `<` must not break the HTML parse mode."""
    custom = await get_custom_paused_message(session, lang)
    return html.escape(custom) if custom is not None else default_paused_message(lang)
