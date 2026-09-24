"""The My Services account-info screen's text.

Every value is live: plan and volume from our own rows, status and
expiry from IBSng via `get_service_status` (never raises), password via
`get_user_password` (guarded here). IBSng stores `nearest_exp_date` in
the Gregorian calendar ("YYYY-MM-DD HH:MM"), and this screen formats the
parsed datetime explicitly as Gregorian, the same calendar every other
screen in this bot uses. Persian lines go through `info_line` so the
RTL label and the LTR value stay aligned on every client.
"""

from __future__ import annotations

import html
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vpn_user import VPNUser
from app.i18n.bidi import info_line
from app.i18n.texts import t
from app.services.catalog import format_data_cap, get_plan, plan_display_name
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.vpn_users import get_service_status

logger = logging.getLogger(__name__)

_STATUS_KEYS = {
    "active": "status_active",
    "expired": "status_expired",
    "pending": "status_pending",
    "unknown": "status_unknown",
}

GREGORIAN_FORMAT = "%Y-%m-%d %H:%M"


def credential_lines(username: str, password: str | None, lang: str) -> str:
    """Tap-to-copy username and password, one bidi-safe line each."""
    password_value = (
        f"<code>{html.escape(password)}</code>" if password else t("info_password_unavailable", lang)
    )
    return "\n".join((
        info_line(t("username_label", lang), f"<code>{html.escape(username)}</code>", lang),
        info_line(t("password_label", lang), password_value, lang),
    ))


async def build_account_info(session: AsyncSession, client: IBSngClient, vpn_user: VPNUser, lang: str) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    name = plan_display_name(plan, lang) if plan is not None else vpn_user.ibsng_group
    status, expiry = await get_service_status(client, vpn_user.ibsng_username)

    if expiry is not None:
        expiry_text = t("info_expiry_value", lang, date=expiry.strftime(GREGORIAN_FORMAT))
    elif status == "pending":
        expiry_text = t("info_expiry_pending", lang)
    else:
        expiry_text = t("info_expiry_unknown", lang)

    try:
        password = await client.get_user_password(username=vpn_user.ibsng_username)
    except IBSngError:
        logger.warning("Account info: could not read the password for %r", vpn_user.ibsng_username)
        password = None

    return "\n".join((
        f"<b>{html.escape(name)}</b> 🔑",
        info_line(t("info_status_label", lang), t(_STATUS_KEYS.get(status, "status_unknown"), lang), lang),
        info_line(t("info_volume_label", lang), format_data_cap(vpn_user.data_cap_mb, lang), lang),
        info_line(t("info_expiry_label", lang), expiry_text, lang),
        "",
        credential_lines(vpn_user.ibsng_username, password, lang),
    ))
