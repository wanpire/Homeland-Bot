from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

router = Router(name="admin_fallback")

NO_PERMISSION_TEXT = "⛔️ You don't have permission for that."
#: Kept module-level and public: app/bot/handlers/admin.py reuses it
#: for the tiers it refuses itself, so the two can never disagree.


@router.callback_query(F.data.startswith("adm:"))
async def admin_unhandled_cb(callback: CallbackQuery) -> None:
    """Safety net for every adm:* callback that reaches here unmatched -
    e.g. a filter-gated route (IsFullAdmin/IsSalesAdmin) silently
    rejecting a lower-tier admin's tap, or a stale keyboard held from
    before a permission change. Registered last among the admin routers
    so it only fires when nothing else claimed the callback - without
    it, Telegram shows an indefinite spinner with zero feedback."""
    await callback.answer(NO_PERMISSION_TEXT, show_alert=True)
