# Bilingual Customer-Facing Flows — Design Spec

Date: 2026-09-18
Status: proposed

## 1. Summary

Every customer-facing flow in Homeland becomes bilingual (Persian/English),
selected once by the customer and reused thereafter, editable later via a
"🌐 Language" button. Admin-facing modules (everything under
`app/bot/handlers/admin*.py`, `admin_settings`, `admin_block`, `broadcast`,
`tutorial_admin`, and the whole `adm:*` screen tree reachable from the "🛠
Admin Panel" button) stay English-only and untouched — including for admins,
who see the same bilingual main menu as any other customer up to the point
they tap into the panel.

This is a lightweight, in-repo approach: two plain Python dicts (one per
language) and a `t(key, lang, **kwargs)` lookup helper — no aiogram-i18n, no
Fluent, no `.po`/`.mo` files. This matches the project's existing style
(plain module-level string constants) and keeps every translation
grep-able and diffable as ordinary Python source.

## 2. Scope

**In scope** (every user-visible string in):
- `app/bot/keyboards/menus.py`, `app/bot/handlers/users.py` (main menu,
  support, the new language screen)
- `app/bot/handlers/buy.py` + `app/bot/keyboards/buy.py`
- `app/bot/handlers/renew.py` + `app/bot/keyboards/renew.py`
- `app/bot/handlers/myservices.py` + `app/bot/keyboards/myservices.py`
- `app/bot/handlers/trial.py` + `app/bot/keyboards/trial.py`
- `app/services/tutorial_delivery.py` (the surrounding chrome only — see
  Boundary 1 below)
- `app/bot/handlers/fallback.py` (no strings of its own — calls
  `send_main_menu`, already covered)
- `app/bot/error_handlers.py` (the pool-busy message)
- `app/webhook.py`'s buyer-visible NOWPayments IPN messages
- `app/services/reminders.py`'s reminder DM
- `app/services/catalog.py` gains `plan_display_name(plan, lang)`

**Out of scope / explicit boundaries:**
1. **Admin-authored free-text content stays single-language.** Tutorial
   guides and connection profiles (`TutorialGuide.body_html`,
   `TutorialProfile.text`, uploaded via `/admintutorials`) are arbitrary
   text an admin typed once — there is no dict entry for content an admin
   wrote, only for the bot's own chrome around it (the "not ready" message,
   the "connection profile" label, the download-link prefix).
2. **Protocol/platform labels stay as-is.** `TutorialProtocol.label`
   (`"OpenVPN"`, `"L2TP"`) and `TutorialPlatform.label` (`"iOS"`,
   `"Android"`) are admin-managed DB rows, not translated — these are
   product/technical names, shown identically in both languages (matching
   how brand/protocol names are conventionally left untranslated in Persian
   tech products).
3. **Numeric/currency formatting helpers stay language-neutral.**
   `format_price_usd`/`format_data_cap` (`app/services/catalog.py`) keep
   returning `"$5.00"` / `"10 GB"` in both languages — units and the `$`
   sign are universal shorthand; only the surrounding prose is translated.
   Numbers written directly inside translated prose (e.g. "24 hours") use
   Persian numerals in the `fa` dict and Latin numerals in `en`, matching
   how AloBot's existing Persian strings already write inline numbers.
4. **"Scroll"/"Stream" category names are transliterated, not translated**
   — they're Homeland's own coined tier names, not ordinary words with a
   Persian equivalent: `اسکرول` / `استریم`. Flagged for your review below;
   easy to change if you'd rather keep them in Latin script even in the
   Persian UI.
5. **Admin-facing modules get zero changes** — verified explicitly in the
   final implementation task (§8 "Leak verification").

## 3. Data model

New migration `0009_bot_user_language.py`:

```python
"""add BotUser.language for bilingual customer-facing flows

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_users", sa.Column("language", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_users", "language")
```

`app/db/models/bot_user.py` gains one field:

```python
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
```

No default — `NULL` means "not chosen yet," which is exactly the signal
the middleware below acts on. No backfill: every existing customer sees the
language chooser on their next interaction, same as any new customer.

`app/services/bot_users.py` gains two functions, alongside the existing
`record_seen`/`is_blocked`/`block_user`:

```python
async def get_language(session: AsyncSession, telegram_id: int) -> str | None:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    return row.language if row is not None else None


async def set_language(session: AsyncSession, telegram_id: int, language: str) -> None:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is not None:
        row.language = language
        await session.commit()
```

## 4. Language resolution: middleware + chooser flow

New `app/bot/middlewares/language.py`, registered in `app/main.py`
immediately after `UserTrackingMiddleware` (so the `BotUser` row already
exists) and before `BlockedUserMiddleware`:

```python
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.bot.keyboards.language import language_choice_keyboard
from app.db.session import async_session_maker
from app.i18n.texts import CHOOSE_LANGUAGE_TEXT
from app.services.bot_users import get_language


class LanguageMiddleware(BaseMiddleware):
    """Gates every update behind a one-time language choice, then attaches
    the resolved language to `data["lang"]` for every handler downstream -
    same interception shape as MandatoryChannelMiddleware, so a customer
    can never reach a handler with data["lang"] unset."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        inner: Message | CallbackQuery | None = event.message or event.callback_query
        if inner is None or inner.from_user is None:
            return await handler(event, data)

        # menu:language and lang:set:* must reach their own handlers even
        # with lang still unset - respectively re-running and answering
        # the chooser itself. Neither handler declares a `lang` parameter
        # (menu_language_cb's CHOOSE_LANGUAGE_TEXT is fixed/bilingual;
        # lang_set_cb parses the target language straight out of its own
        # callback_data), so there is nothing to attach to `data` here.
        callback_data = inner.data if isinstance(inner, CallbackQuery) else None
        if callback_data == "menu:language" or (callback_data or "").startswith("lang:set:"):
            return await handler(event, data)

        async with async_session_maker() as session:
            lang = await get_language(session, inner.from_user.id)

        if lang is None:
            if isinstance(inner, CallbackQuery):
                if inner.message is not None:
                    await inner.message.edit_text(CHOOSE_LANGUAGE_TEXT, reply_markup=language_choice_keyboard())
                await inner.answer()
            else:
                await inner.answer(CHOOSE_LANGUAGE_TEXT, reply_markup=language_choice_keyboard())
            return None

        data["lang"] = lang
        return await handler(event, data)
```

New `app/bot/keyboards/language.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def language_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇮🇷 فارسی", callback_data="lang:set:fa")
    builder.button(text="🇬🇧 English", callback_data="lang:set:en")
    builder.adjust(2)
    return builder.as_markup()
```

Handlers that render the main menu get `lang` for free via aiogram's
existing data-dict injection — the same mechanism `state: FSMContext`
already relies on in this codebase; a handler just declares a `lang: str`
parameter and aiogram supplies `data["lang"]` automatically. `main_menu()`
gains a `lang` parameter (translating every button via `t()`);
`send_main_menu` keeps its existing internal `is_admin` computation
unchanged and only gains `lang`, threaded through by its callers:

```python
async def send_main_menu(target: Message, *, lang: str) -> None:
    is_admin = await _is_admin(target.from_user.id) if target.from_user else False
    await target.answer(t("welcome", lang), reply_markup=main_menu(is_admin=is_admin, lang=lang))


@router.message(Command("start"))
async def start_cmd(message: Message, lang: str) -> None:
    await send_main_menu(message, lang=lang)


@router.callback_query(F.data == "menu:root")
async def menu_root_cb(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        is_admin = await _is_admin(callback.from_user.id)
        await callback.message.edit_text(t("welcome", lang), reply_markup=main_menu(is_admin=is_admin, lang=lang))
    await callback.answer()


@router.callback_query(F.data == "menu:language")
async def menu_language_cb(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(CHOOSE_LANGUAGE_TEXT, reply_markup=language_choice_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("lang:set:"))
async def lang_set_cb(callback: CallbackQuery) -> None:
    lang = callback.data.split(":")[-1]
    if lang not in ("fa", "en"):
        lang = "en"
    async with async_session_maker() as session:
        await set_language(session, callback.from_user.id, lang)
    if callback.message is not None:
        await callback.message.edit_text(t("language_updated", lang))
        await send_main_menu(callback.message, lang=lang)
    await callback.answer()
```

`app/bot/handlers/fallback.py`'s `fallback_to_main_menu` gets the same
treatment — a new `lang: str` parameter, injected, threaded into its
existing `send_main_menu(message)` call as `send_main_menu(message, lang=lang)`.

Main menu gains one button, "🌐 Language" (English UI) / "🌐 زبان" (Persian
UI) → `menu:language`, placed after Support.

## 5. i18n infrastructure

New package `app/i18n/`:

- `app/i18n/__init__.py` — empty.
- `app/i18n/texts.py` — the two dicts plus `t()`.

```python
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_LANG = "en"

TEXTS: dict[str, dict[str, str]] = {
    "en": { ... },  # full key set in §7
    "fa": { ... },
}

CHOOSE_LANGUAGE_TEXT = (
    "🇮🇷 فارسی / 🇬🇧 English\n\n"
    "لطفاً زبان خود را انتخاب کنید:\n"
    "Please choose your language:"
)


def t(key: str, lang: str, **kwargs: object) -> str:
    """Never raises - a missing key or a missing language falls back to
    English (logged as a warning), and a key missing from English too
    returns the bare key itself so a broken lookup is visible in the
    chat rather than crashing the handler."""
    lang_dict = TEXTS.get(lang, TEXTS[DEFAULT_LANG])
    template = lang_dict.get(key)
    if template is None:
        if lang != DEFAULT_LANG:
            logger.warning("Missing i18n key %r for lang=%r, falling back to %r", key, lang, DEFAULT_LANG)
        template = TEXTS[DEFAULT_LANG].get(key)
    if template is None:
        logger.warning("Missing i18n key %r in every language", key)
        return key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        logger.warning("i18n key %r formatting failed with kwargs=%r", key, kwargs)
        return template
```

`CHOOSE_LANGUAGE_TEXT` is a module-level constant, not a `t()` key — it is
shown to someone whose language is, by definition, not yet known, so it
must always render both scripts together regardless of any stored value.

## 6. Plan display names

`Plan.name` only ever takes 5 distinct values across all 7 seeded plans
("Trial", "2 Weeks", "1 Month", "2 Months", "3 Months" — confirmed against
`alembic/versions/0004_correct_catalog_to_real_groups.py`), so
`plan_display_name` maps the *name string itself*, not a per-plan-id table
— simpler, and automatically correct if a future plan reuses an existing
duration phrase.

`app/services/catalog.py` gains:

```python
_PLAN_NAME_KEYS = {
    "Trial": "plan_name_trial",
    "2 Weeks": "plan_name_2weeks",
    "1 Month": "plan_name_1month",
    "2 Months": "plan_name_2months",
    "3 Months": "plan_name_3months",
}

_CATEGORY_KEYS = {"scroll": "category_scroll", "stream": "category_stream", "trial": "category_trial"}


def plan_display_name(plan: Plan, lang: str) -> str:
    key = _PLAN_NAME_KEYS.get(plan.name)
    return t(key, lang) if key is not None else plan.name


def category_display_name(category: str, lang: str) -> str:
    key = _CATEGORY_KEYS.get(category)
    return t(key, lang) if key is not None else category.title()
```

Both fall back to the raw English value if the input is ever something
this mapping doesn't recognize (a future plan/category added without a
matching i18n key) — never raises, never shows a blank string.

## 7. Complete translation key table

Every key below is used in at least one module from §2's in-scope list.
Grouped by module for review; the actual file is one flat dict per
language (grep-friendly, not nested).

```python
TEXTS: dict[str, dict[str, str]] = {
    "en": {
        # --- main menu / users.py ---
        "welcome": "👋 Welcome to Homeland VPN.\n\nChoose an option below:",
        "menu_buy": "🔑 Buy Subscription",
        "menu_renew": "♻️ Renew Service",
        "menu_trial": "🎁 Free Trial",
        "menu_myservices": "🛍 My Services",
        "menu_tutorials": "📚 Tutorials",
        "menu_support": "☎️ Support",
        "menu_language": "🌐 Language",
        "placeholder_coming_soon": "🚧 This feature is coming soon.",
        "support_heading": "☎️ <b>Support</b>\n\nTap the button below to contact support.",
        "support_not_configured": "☎️ Support contact isn't configured yet. Please check back soon.",
        "contact_support_button": "☎️ Contact Support",
        "back_to_menu": "⬅️ Back to Menu",
        "language_updated": "✅ Language updated.",

        # --- buy.py / buy keyboard ---
        "buy_category_heading": "🔑 <b>Buy Subscription</b>\n\nPick a category:",
        "buy_pick_plan": "Pick a plan:",
        "category_scroll": "📜 Scroll",
        "category_stream": "🌊 Stream",
        "category_trial": "Trial",
        "plan_gone": "⚠️ That plan no longer exists. Please pick another.",
        "payment_coming_soon": (
            "🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know "
            "the moment they're live. No charge has been made and no account was created."
        ),
        "payment_link_heading": (
            "💳 <b>Complete your payment</b>\n\n"
            "Tap below to open the payment page — you'll be able to choose your "
            "coin and network there. We'll confirm automatically once payment is "
            "received; no need to come back and check."
        ),
        "payment_unavailable": (
            "⚠️ We couldn't reach the payment provider right now. Please try again "
            "in a few minutes, or contact support if this keeps happening."
        ),
        "pay_with_crypto_button": "₿ Pay with Crypto",
        "open_payment_page_button": "🔗 Open Payment Page",
        "back_button": "⬅️ Back",
        "price_duration": "Duration: {days} days",
        "price_data": "Data: {cap}",
        "price_line": "Price: {price}",
        "price_line_discounted": "Price: <s>{original}</s> {discounted} (-{percent}%)",

        # --- renew.py / renew keyboard ---
        "renew_list_heading": "♻️ <b>Renew Service</b>\n\nWhich service do you want to renew?",
        "renew_empty": "♻️ <b>Renew Service</b>\n\nYou don't have any services to renew yet.",
        "renew_not_found": "⚠️ Service not found.",
        "renew_pick_category": "♻️ <b>Renew {name}</b>\n\nPick a category:",
        "renew_pick_plan": "♻️ <b>Renew {name}</b>\n\nPick a plan:",
        "renew_summary_heading": "♻️ <b>Renew {current} → {new} ({category})</b>",
        "payment_coming_soon_renew": (
            "🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know "
            "the moment they're live. No charge has been made and your service has not "
            "been changed."
        ),

        # --- myservices.py / myservices keyboard ---
        "myservices_heading": "🛍 <b>My Services</b>",
        "myservices_empty": "🛍 <b>My Services</b>\n\nYou don't have any services yet.",
        "myservices_not_found": "⚠️ Service not found.",
        "status_active": "✅ Active",
        "status_expired": "⛔ Expired",
        "status_pending": "⏳ Pending",
        "status_unknown": "⚠️ Unknown",
        "status_line_active": "Status: ✅ Active until {date} UTC",
        "status_line_expired": "Status: ⛔ Expired on {date} UTC",
        "status_line_pending": "Status: ⏳ Not yet activated — validity starts on first connection.",
        "status_line_unknown": "Status: ⚠️ Couldn't check status right now.",
        "password_unavailable": "Password: unavailable — contact support",
        "protocol_prompt": "🔌 Which protocol do you want to use?",
        "platform_prompt": "📱 Which device do you want to set it up on?",
        "resent_confirmation": "✅ Sent — check the message above.",
        "resend_blocked": "⚠️ See the message above for details.",
        "resend_setup_button": "🔄 Resend Setup",
        "back_to_list_button": "⬅️ Back to List",
        "back_to_service_button": "⬅️ Back to Service",

        # --- trial.py / trial keyboard ---
        "trial_already_used": "🎁 You've already used your free trial.",
        "trial_confirm_prompt": "🎁 <b>Free Trial</b> — 24 hours, 1GB of data.\n\nStart your trial?",
        "trial_create_failed": "⚠️ Couldn't create your trial right now. Please try again shortly.",
        "trial_credentials_unavailable": (
            "⚠️ Your trial account was created, but we couldn't retrieve your "
            "credentials right now. Please contact support and they'll send them to you."
        ),
        "trial_ready": (
            "🎁 <b>Your trial is ready.</b>\n\n"
            "Username: <code>{username}</code>\n"
            "Password: <code>{password}</code>\n\n"
            "⏱ Valid for 24 hours from first connection."
        ),
        "confirm_button": "✅ Confirm",

        # --- tutorial_delivery.py ---
        "android_l2tp_unsupported": (
            "⚠️ L2TP isn't supported on Android 12 and newer (Google removed the "
            "built-in L2TP/IPsec client). Please use OpenVPN instead, or contact "
            "support for help."
        ),
        "guide_not_ready": "📚 This guide is not ready yet — please contact support.",
        "connection_profile_prefix": "📡 Connection profile ({name})",
        "download_link_prefix": "📥 App download link:",
        "download_openvpn_links_heading": "📥 Download OpenVPN Connect:",
        "any_platform_label": "Any platform:",

        # --- webhook.py ---
        "payment_confirmed": "🎉 Payment confirmed! Your service (<code>{username}</code>) has been {action}.",
        "action_activated": "activated",
        "action_renewed": "renewed",
        "partial_payment": (
            "⚠️ We received a partial payment — it wasn't quite enough to complete your order, "
            "so your service hasn't been activated yet. Tap below to finish paying the remaining "
            "balance; the page will show exactly how much is left."
        ),
        "payment_failed": (
            "❌ This payment did not complete. You can start over any time from "
            "Buy Subscription or Renew Service."
        ),
        "activation_technical_issue": (
            "⚠️ Your payment was received, but we hit a technical issue activating your "
            "service. Please contact support with your payment date and amount."
        ),
        "finish_payment_button": "💰 Finish Payment",

        # --- error_handlers.py ---
        "pool_busy": "⏳ The server is temporarily busy. Please try again shortly.",

        # --- reminders.py ---
        "reminder_message": (
            "⏰ Your VPN service (<code>{username}</code>) expires in less than "
            "{days} day(s). Renew now to avoid interruption."
        ),
        "renew_now_button": "♻️ Renew Now",

        # --- plan display names (catalog.py) ---
        "plan_name_trial": "Trial",
        "plan_name_2weeks": "2 Weeks",
        "plan_name_1month": "1 Month",
        "plan_name_2months": "2 Months",
        "plan_name_3months": "3 Months",
    },
    "fa": {
        "welcome": "👋 به Homeland VPN خوش آمدید.\n\nیکی از گزینه‌های زیر را انتخاب کنید:",
        "menu_buy": "🔑 خرید اشتراک",
        "menu_renew": "♻️ تمدید سرویس",
        "menu_trial": "🎁 تست رایگان",
        "menu_myservices": "🛍 سرویس‌های من",
        "menu_tutorials": "📚 آموزش‌ها",
        "menu_support": "☎️ پشتیبانی",
        "menu_language": "🌐 زبان",
        "placeholder_coming_soon": "🚧 این قابلیت به‌زودی اضافه می‌شود.",
        "support_heading": "☎️ <b>پشتیبانی</b>\n\nبرای تماس با پشتیبانی روی دکمه زیر بزنید.",
        "support_not_configured": "☎️ اطلاعات تماس پشتیبانی هنوز تنظیم نشده. لطفاً بعداً دوباره سر بزنید.",
        "contact_support_button": "☎️ تماس با پشتیبانی",
        "back_to_menu": "⬅️ بازگشت به منو",
        "language_updated": "✅ زبان با موفقیت تغییر کرد.",

        "buy_category_heading": "🔑 <b>خرید اشتراک</b>\n\nیک دسته را انتخاب کنید:",
        "buy_pick_plan": "یک پلن را انتخاب کنید:",
        "category_scroll": "📜 اسکرول",
        "category_stream": "🌊 استریم",
        "category_trial": "تست رایگان",
        "plan_gone": "⚠️ این پلن دیگر وجود ندارد. لطفاً پلن دیگری انتخاب کنید.",
        "payment_coming_soon": (
            "🚧 روش‌های پرداخت (استرایپ، ارز دیجیتال) به‌زودی فعال می‌شوند — به محض "
            "فعال شدن به شما اطلاع می‌دهیم. هیچ مبلغی کسر نشده و حسابی ساخته نشده است."
        ),
        "payment_link_heading": (
            "💳 <b>تکمیل پرداخت</b>\n\n"
            "برای باز کردن صفحه پرداخت روی دکمه زیر بزنید — می‌توانید ارز و شبکه دلخواه "
            "خود را همان‌جا انتخاب کنید. پس از دریافت پرداخت به‌صورت خودکار تأیید می‌شود؛ "
            "نیازی به بازگشت و بررسی دستی نیست."
        ),
        "payment_unavailable": (
            "⚠️ در حال حاضر امکان اتصال به درگاه پرداخت وجود ندارد. لطفاً چند دقیقه دیگر "
            "دوباره امتحان کنید یا در صورت تکرار با پشتیبانی تماس بگیرید."
        ),
        "pay_with_crypto_button": "₿ پرداخت با ارز دیجیتال",
        "open_payment_page_button": "🔗 باز کردن صفحه پرداخت",
        "back_button": "⬅️ بازگشت",
        "price_duration": "مدت: {days} روز",
        "price_data": "حجم: {cap}",
        "price_line": "قیمت: {price}",
        "price_line_discounted": "قیمت: <s>{original}</s> {discounted} (-{percent}٪)",

        "renew_list_heading": "♻️ <b>تمدید سرویس</b>\n\nکدام سرویس را می‌خواهید تمدید کنید؟",
        "renew_empty": "♻️ <b>تمدید سرویس</b>\n\nهنوز سرویسی برای تمدید ندارید.",
        "renew_not_found": "⚠️ سرویس یافت نشد.",
        "renew_pick_category": "♻️ <b>تمدید {name}</b>\n\nیک دسته را انتخاب کنید:",
        "renew_pick_plan": "♻️ <b>تمدید {name}</b>\n\nیک پلن را انتخاب کنید:",
        "renew_summary_heading": "♻️ <b>تمدید {current} → {new} ({category})</b>",
        "payment_coming_soon_renew": (
            "🚧 روش‌های پرداخت (استرایپ، ارز دیجیتال) به‌زودی فعال می‌شوند — به محض فعال "
            "شدن به شما اطلاع می‌دهیم. هیچ مبلغی کسر نشده و سرویس شما تغییری نکرده است."
        ),

        "myservices_heading": "🛍 <b>سرویس‌های من</b>",
        "myservices_empty": "🛍 <b>سرویس‌های من</b>\n\nهنوز سرویسی ندارید.",
        "myservices_not_found": "⚠️ سرویس یافت نشد.",
        "status_active": "✅ فعال",
        "status_expired": "⛔ منقضی‌شده",
        "status_pending": "⏳ در انتظار",
        "status_unknown": "⚠️ نامشخص",
        "status_line_active": "وضعیت: ✅ فعال تا {date} UTC",
        "status_line_expired": "وضعیت: ⛔ منقضی‌شده در {date} UTC",
        "status_line_pending": "وضعیت: ⏳ هنوز فعال نشده — اعتبار از اولین اتصال شروع می‌شود.",
        "status_line_unknown": "وضعیت: ⚠️ در حال حاضر امکان بررسی وضعیت وجود ندارد.",
        "password_unavailable": "رمز عبور: در دسترس نیست — با پشتیبانی تماس بگیرید",
        "protocol_prompt": "🔌 کدام پروتکل را می‌خواهید استفاده کنید؟",
        "platform_prompt": "📱 روی کدام دستگاه می‌خواهید تنظیم کنید؟",
        "resent_confirmation": "✅ ارسال شد — پیام بالا را بررسی کنید.",
        "resend_blocked": "⚠️ برای جزئیات پیام بالا را بررسی کنید.",
        "resend_setup_button": "🔄 ارسال مجدد تنظیمات",
        "back_to_list_button": "⬅️ بازگشت به لیست",
        "back_to_service_button": "⬅️ بازگشت به سرویس",

        "trial_already_used": "🎁 شما قبلاً از تست رایگان خود استفاده کرده‌اید.",
        "trial_confirm_prompt": "🎁 <b>تست رایگان</b> — ۲۴ ساعت، ۱ گیگابایت حجم.\n\nتست رایگان را شروع می‌کنید؟",
        "trial_create_failed": "⚠️ در حال حاضر امکان ایجاد تست رایگان وجود ندارد. لطفاً کمی بعد دوباره امتحان کنید.",
        "trial_credentials_unavailable": (
            "⚠️ حساب تست رایگان شما ساخته شد، اما در حال حاضر امکان دریافت اطلاعات ورود "
            "وجود ندارد. با پشتیبانی تماس بگیرید تا برایتان ارسال شود."
        ),
        "trial_ready": (
            "🎁 <b>تست رایگان شما آماده است.</b>\n\n"
            "نام کاربری: <code>{username}</code>\n"
            "رمز عبور: <code>{password}</code>\n\n"
            "⏱ به مدت ۲۴ ساعت از اولین اتصال معتبر است."
        ),
        "confirm_button": "✅ تأیید",

        "android_l2tp_unsupported": (
            "⚠️ پروتکل L2TP روی اندروید ۱۲ به بعد پشتیبانی نمی‌شود (گوگل کلاینت داخلی "
            "L2TP/IPsec را حذف کرده است). لطفاً از OpenVPN استفاده کنید یا برای راهنمایی "
            "با پشتیبانی تماس بگیرید."
        ),
        "guide_not_ready": "📚 این راهنما هنوز آماده نیست — لطفاً با پشتیبانی تماس بگیرید.",
        "connection_profile_prefix": "📡 پروفایل اتصال ({name})",
        "download_link_prefix": "📥 لینک دانلود اپلیکیشن:",
        "download_openvpn_links_heading": "📥 دانلود OpenVPN Connect:",
        "any_platform_label": "همه دستگاه‌ها:",

        "payment_confirmed": "🎉 پرداخت تأیید شد! سرویس شما (<code>{username}</code>) {action} شد.",
        "action_activated": "فعال",
        "action_renewed": "تمدید",
        "partial_payment": (
            "⚠️ پرداخت جزئی دریافت شد — مبلغ کافی برای تکمیل سفارش نبود، بنابراین سرویس "
            "شما هنوز فعال نشده است. برای تکمیل باقی‌مانده مبلغ روی دکمه زیر بزنید؛ صفحه "
            "پرداخت مبلغ دقیق باقی‌مانده را نشان می‌دهد."
        ),
        "payment_failed": (
            "❌ این پرداخت تکمیل نشد. می‌توانید هر زمان از «خرید اشتراک» یا «تمدید سرویس» "
            "دوباره شروع کنید."
        ),
        "activation_technical_issue": (
            "⚠️ پرداخت شما دریافت شد، اما در فعال‌سازی سرویس با یک مشکل فنی مواجه شدیم. "
            "لطفاً همراه با تاریخ و مبلغ پرداخت با پشتیبانی تماس بگیرید."
        ),
        "finish_payment_button": "💰 تکمیل پرداخت",

        "pool_busy": "⏳ سرور موقتاً شلوغ است. لطفاً کمی بعد دوباره امتحان کنید.",

        "reminder_message": (
            "⏰ اعتبار سرویس شما (<code>{username}</code>) کمتر از {days} روز دیگر تمام "
            "می‌شود. برای جلوگیری از قطعی همین حالا تمدید کنید."
        ),
        "renew_now_button": "♻️ تمدید کنید",

        "plan_name_trial": "تست رایگان",
        "plan_name_2weeks": "۲ هفته",
        "plan_name_1month": "۱ ماه",
        "plan_name_2months": "۲ ماه",
        "plan_name_3months": "۳ ماه",
    },
}
```

**Key-set parity check:** both dicts define exactly the same 83 keys, with
matching `.format()` placeholders on every key that interpolates a value —
verified with a script that actually parses both dicts and diffs their key
sets and placeholder sets, not eyeballed. Zero mismatches, zero duplicate
keys within either dict.

## 8. Out-of-band language lookups

Three code paths send messages to a customer without ever going through
`LanguageMiddleware`, so each needs its own explicit language lookup:

1. **`app/webhook.py`** (`_handle_crypto_ipn`, `_notify_activation_technical_issue`) —
   runs inside the aiohttp app, not the aiogram dispatcher. Add
   `lang = await get_language(session, payment.telegram_id)` (falling back
   to `"en"` if `None` — a payment webhook can fire before the customer
   ever opens the bot again) right before each `t()` call; the `session`
   already open in `_handle_crypto_ipn` covers this with no new query cost
   beyond the two already-open-session cases.
2. **`app/services/reminders.py`** (`send_due_reminders`) — the existing
   per-candidate loop already holds a `session`; add the same
   `get_language(...)` call (default `"en"`) before formatting the
   reminder text.
3. **`app/bot/error_handlers.py`** (`handle_pool_timeout`) — a global
   error handler registered via `dp.errors.register(...)`, not a normal
   middleware-wrapped handler. aiogram's `ErrorsMiddleware` re-injects the
   original update's `data` dict into the error handler's kwargs, so
   `data["lang"]` set by `LanguageMiddleware` earlier in the same update's
   processing IS available — add `data: dict` (or a narrower typed param
   aiogram supports injecting) to `handle_pool_timeout`'s signature and
   read `data.get("lang", "en")`. **Verify this during implementation**
   (write a test that triggers a pool timeout with `lang="fa"` in a
   pre-seeded `BotUser` row and asserts the Persian message renders) —
   if the injection doesn't work as expected, fall back to a direct
   `get_language(session, chat_id)` query using `chat_id` as the
   telegram_id (safe: `PrivateChatOnlyMiddleware` already guarantees every
   update here is a 1:1 DM, so `chat_id == telegram_id`).

Additionally, `app/services/tutorial_delivery.py`'s `deliver_setup()` and
`app/bot/handlers/trial.py`'s `_send_trial_credentials()` both run inside a
real handler (so `lang` IS available in `data`) but are plain functions,
not handlers themselves — both need an explicit `lang: str` parameter
threaded through from every call site (2 in `trial.py`, 2 in
`myservices.py`) rather than re-deriving it from a session query.

## 9. `CLAUDE.md` and skill-doc updates

**`CLAUDE.md`** (Conventions section):

```diff
-- All user-facing AND admin-facing strings in English.
+- Customer-facing strings are bilingual (fa/en) via app/i18n/texts.py's
+  t(key, lang) - see docs/superpowers/specs/2026-09-18-bilingual-customer-
+  flows-design.md. Admin-facing strings (everything under
+  app/bot/handlers/admin*.py, admin_settings, admin_block, broadcast,
+  tutorial_admin, and the adm:* screen tree) stay English-only - never
+  route an admin-only string through t().
```

**`.claude/skills/aiogram-menu-flow-conventions/SKILL.md`** also documents
the now-superseded rule and must be updated in the same task, not just
`CLAUDE.md` — discovered mid-spec-writing (its "English-only copy"
section states Homeland is deliberately English-only because it sells to
customers living *abroad*, unlike AloBot's in-Iran Persian audience;
confirmed with you that this no longer holds). Replace that section's
content with the same customer-facing/admin-facing split described above,
so the skill doesn't contradict this spec for the next person or session
that loads it.

## 10. Testing strategy

Every module task in the implementation plan adds/updates tests in its
own commit, following the existing `tests/functional/` pattern (real
dispatcher via `feed_update`, not mocks). Minimum coverage per the plan:
- Language selection: a brand-new `BotUser` (language `NULL`) sees the
  chooser instead of the main menu on `/start`; tapping "🇮🇷 فارسی" sets
  `language="fa"` and shows the Persian main menu; tapping "🌐 Language"
  later re-runs the chooser and updates the stored value.
- For each migrated module: one test asserting the `fa` path renders
  (seed `BotUser(language="fa")` first) alongside the module's existing
  English-path tests (which continue to pass unmodified, proving `en`
  stays the correct default/fallback).
- `t()` unit tests: missing key falls back to English + logs a warning;
  key missing everywhere returns the bare key; a `.format()` mismatch
  doesn't raise.
- A key-set-parity test: `set(TEXTS["en"]) == set(TEXTS["fa"])`, so a
  future PR that adds an English string without its Persian counterpart
  fails CI immediately rather than silently falling back at runtime.
- Reminder notification: seed a `BotUser(language="fa")` with a due
  reminder, assert the sent message is the Persian template.
- Leak-verification task (§2 boundary 5): a test asserting every admin
  handler module's source contains zero references to `app.i18n` (a
  simple `grep`/`ast`-based check is enough — not a runtime test).

## 11. Self-review

**Placeholder scan:** no TBD/TODO; every key in §7 has real English and
Persian text, not a stub.

**Internal consistency:** the middleware's placement (after
`UserTrackingMiddleware`, before `BlockedUserMiddleware`) matches §4's
prose and the exception carved out for `menu:language`/`lang:set:*` so a
user picking their language for the first time isn't caught in its own
gate. `plan_display_name`/`category_display_name`'s fallback-to-raw-value
behavior matches `t()`'s own never-raise guarantee.

**Scope check:** appropriately sized for one plan — infrastructure (data
model + middleware + i18n module) is 1-2 tasks, then one task per
already-enumerated module (8 modules), then the leak-verification task.
Each task is independently testable and independently committable,
matching the "separate, reviewable commits" requirement.

**Ambiguity check, flagged for your review specifically (not blocking,
easy to change during spec review):**
- "Scroll"/"Stream" transliterated as اسکرول/استریم (§2 boundary 4) rather
  than left in Latin script or given a descriptive Persian name — your
  call if you'd prefer something else.
- Persian numerals used for small numbers written directly in prose
  (`۲۴ ساعت`, `۱ گیگابایت`) while shared formatting helpers
  (`format_price_usd`/`format_data_cap`) keep Latin digits — flagged in
  case you'd rather keep every number in Latin digits throughout for a
  more "technical" register.
- `payment_coming_soon` (buy.py) and `payment_coming_soon_renew` (renew.py)
  are two separate keys, not one shared key, because their English source
  text already differs by one clause ("no account was created" vs "your
  service has not been changed") — preserving that existing distinction
  rather than collapsing it.
