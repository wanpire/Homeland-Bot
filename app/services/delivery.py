"""The ONE account-delivery message.

Three flows hand a customer a working account - a new purchase, a
renewal, and a free trial - and every one of them sends this. The
headline differs, and so does the ending: purchase and renewal close
with a pointer to the Tutorial section and the Tutorial/main-menu
buttons, while a trial's message is one step of a device-first sequence
(see app/bot/handlers/trial.py) that ends on the chosen device's setup
material, so it carries neither and the trial attaches the buttons to
its own last message. The body and credential formatting are identical,
so there is a single template per language to keep correct rather than
three that drift apart.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from app.bot.keyboards.delivery import order_delivered_keyboard
from app.db.models.plan import Plan
from app.i18n.texts import t
from app.services.catalog import format_data_cap, plan_display_name

logger = logging.getLogger(__name__)

PURCHASE = "purchase"
RENEWAL = "renewal"
TRIAL = "trial"

_HEADLINE_KEYS = {
    PURCHASE: "delivery_headline_purchase",
    RENEWAL: "delivery_headline_renewal",
    TRIAL: "delivery_headline_trial",
}


def build_delivery_text(
    *,
    kind: str,
    plan: Plan | None,
    data_cap_mb: int,
    username: str,
    password: str | None,
    lang: str,
    fallback_plan_name: str = "—",
) -> str:
    """Headline plus the shared body. Kept separate from sending so a
    test can read the text without a Bot, and so a future caller can
    embed it somewhere other than a message."""
    headline = t(_HEADLINE_KEYS.get(kind, _HEADLINE_KEYS[PURCHASE]), lang)
    days = plan.duration_days if plan is not None else 0
    fields = {
        "plan": plan_display_name(plan, lang) if plan is not None else fallback_plan_name,
        "days": days,
        # English needs "1 day" but "30 days"; Persian uses روز for both,
        # so the choice is a key pair rather than an English-only suffix.
        "day_word": t("day_singular" if days == 1 else "day_plural", lang),
        "volume": format_data_cap(data_cap_mb, lang),
        "username": username,
    }
    if password:
        body = t("delivery_body", lang, password=password, **fields)
    else:
        body = t("delivery_body_no_password", lang, **fields)
    text = f"{headline}\n\n{body}"
    if kind != TRIAL:
        text += f"\n\n{t('delivery_tutorial_note', lang)}"
    return text


async def send_account_delivery(
    bot: Bot,
    telegram_id: int,
    *,
    kind: str,
    plan: Plan | None,
    data_cap_mb: int,
    username: str,
    password: str | None,
    lang: str,
    fallback_plan_name: str = "—",
) -> int | None:
    """`data_cap_mb` is passed in rather than read off `plan` on purpose:
    a paid order delivers the snapshot stored on its payment, so an admin
    editing the catalog mid-purchase cannot change what that buyer was
    sold, while a trial passes the trial plan's own value.

    Returns the sent message's id, or None if the bot is blocked."""
    text = build_delivery_text(
        kind=kind,
        plan=plan,
        data_cap_mb=data_cap_mb,
        username=username,
        password=password,
        lang=lang,
        fallback_plan_name=fallback_plan_name,
    )
    reply_markup = None if kind == TRIAL else order_delivered_keyboard(lang)
    try:
        message = await bot.send_message(telegram_id, text, reply_markup=reply_markup)
    except TelegramForbiddenError:
        # The account IS provisioned; the customer has merely blocked the
        # bot. Never let that look like a delivery failure upstream.
        logger.warning("Delivery message not sent to %s (%s) - bot is blocked", telegram_id, kind)
        return None
    return message.message_id
