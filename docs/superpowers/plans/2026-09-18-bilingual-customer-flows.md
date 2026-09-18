# Bilingual Customer-Facing Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every customer-facing flow in Homeland renders in the customer's chosen language (Persian or English), selected once and changeable later; admin-facing modules stay English-only and untouched.

**Architecture:** A new `BotUser.language` column + a `LanguageMiddleware` (mirroring `MandatoryChannelMiddleware`'s gate-and-attach-to-data shape) resolve the customer's language once per update and inject it into every handler as a `lang: str` parameter. A lightweight `app/i18n/texts.py` module (two plain dicts + a never-raising `t(key, lang, **kwargs)` lookup) replaces hardcoded English string constants module by module.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, Alembic, pytest+pytest-asyncio — no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-18-bilingual-customer-flows-design.md`

## Global Constraints

- Customer-facing modules only: `app/bot/keyboards/menus.py`, `app/bot/handlers/users.py`, `buy.py`+`app/bot/keyboards/buy.py`, `renew.py`+`app/bot/keyboards/renew.py`, `myservices.py`+`app/bot/keyboards/myservices.py`, `trial.py`+`app/bot/keyboards/trial.py`, `app/services/tutorial_delivery.py`, `app/bot/handlers/fallback.py`, `app/bot/error_handlers.py`, `app/webhook.py`'s buyer-visible messages, `app/services/reminders.py`'s reminder DM, `app/services/catalog.py`'s new display-name helpers.
- Admin-facing modules (everything under `app/bot/handlers/admin*.py`, `admin_settings`, `admin_block`, `broadcast`, `tutorial_admin`, and the whole `adm:*` screen tree) get **zero changes** — verified by a dedicated leak-verification test in the final task.
- No aiogram-i18n, no Fluent, no `.po`/`.mo` files — two plain dicts (`app/i18n/texts.py`) and a `t()` lookup, matching the project's existing plain-constants style.
- Admin-authored free-text content (`TutorialGuide.body_html`, `TutorialProfile.text`) and `TutorialProtocol.label`/`TutorialPlatform.label` stay untranslated — no `t()` key for content an admin typed or a protocol/device name.
- `format_price_usd`/`format_data_cap` stay language-neutral (`"$5.00"`, `"10 GB"`) in both languages.
- **Test-infrastructure requirement, load-bearing for every task after Task 2:** once `LanguageMiddleware` is registered, a fresh `BotUser` row (`language IS NULL`, the default for every test unless a test says otherwise) would make every existing dispatcher-driven test hit the language chooser instead of its real target. Task 2 adds an **autouse** `tests/conftest.py` fixture that defaults language resolution to `"en"` in tests unless a test explicitly overrides it — a test-fixture-only fix (matching this project's `ibsng_server` fixture precedent: fake the cross-cutting concern, never touch production code to make tests pass). Full existing suite must be green immediately after this fixture lands, before any further step in Task 2.
- **Two keyboard functions are shared across modules that migrate in separate tasks**, so each gets a `lang: str = "en"` default the first time it's touched, letting not-yet-migrated callers keep compiling and rendering English until their own task lands:
  - `back_to_menu_keyboard` (`app/bot/keyboards/trial.py`) — called from `trial.py`, `myservices.py`, `buy.py`, `renew.py`. Gains its default in Task 3.
  - `payment_link_keyboard` (`app/bot/keyboards/buy.py`) — called from `buy.py` and `renew.py`. Gains its default in Task 5.
  - `deliver_setup()` (`app/services/tutorial_delivery.py`) — called from `trial.py` and `myservices.py`. Gains `lang: str = "en"` in Task 3.
  - Every other keyboard-builder function touched in this plan is module-private (called only from within its own handler file) and takes a required `lang` param immediately — no default needed.

---

## File Structure

- **Create** `alembic/versions/0009_bot_user_language.py` — the `BotUser.language` migration.
- **Modify** `app/db/models/bot_user.py` — add the `language` field.
- **Modify** `app/services/bot_users.py` — add `get_language`/`set_language`.
- **Create** `app/i18n/__init__.py`, `app/i18n/texts.py` — the two dicts, `t()`, `CHOOSE_LANGUAGE_TEXT`.
- **Modify** `app/services/catalog.py` — add `plan_display_name`/`category_display_name`.
- **Create** `app/bot/middlewares/language.py`, `app/bot/keyboards/language.py`.
- **Modify** `app/bot/handlers/users.py`, `app/bot/keyboards/menus.py`, `app/bot/handlers/fallback.py`, `app/main.py`.
- **Modify** `tests/conftest.py` — the language-default test fixture.
- **Modify** `app/bot/handlers/trial.py`, `app/bot/keyboards/trial.py`, `app/services/tutorial_delivery.py`.
- **Modify** `app/bot/handlers/myservices.py`, `app/bot/keyboards/myservices.py`.
- **Modify** `app/bot/handlers/buy.py`, `app/bot/keyboards/buy.py`.
- **Modify** `app/bot/handlers/renew.py`, `app/bot/keyboards/renew.py`.
- **Modify** `app/webhook.py`, `app/services/reminders.py`, `app/bot/error_handlers.py`.
- **Modify** `CLAUDE.md`, `.claude/skills/aiogram-menu-flow-conventions/SKILL.md`.

---

## Task 1: Data model + i18n infrastructure

**Files:**
- Create: `alembic/versions/0009_bot_user_language.py`
- Modify: `app/db/models/bot_user.py`
- Modify: `app/services/bot_users.py`
- Create: `app/i18n/__init__.py`, `app/i18n/texts.py`
- Modify: `app/services/catalog.py`
- Test: `tests/functional/test_i18n.py` (new), `tests/functional/test_bot_users.py` (new or append if it exists), `tests/functional/test_catalog.py` (append)

**Interfaces:**
- Produces: `get_language(session, telegram_id) -> str | None`, `set_language(session, telegram_id, language: str) -> None` (`app/services/bot_users.py`); `TEXTS: dict[str, dict[str, str]]`, `DEFAULT_LANG = "en"`, `t(key: str, lang: str, **kwargs) -> str`, `CHOOSE_LANGUAGE_TEXT: str` (`app/i18n/texts.py`); `plan_display_name(plan: Plan, lang: str) -> str`, `category_display_name(category: str, lang: str) -> str` (`app/services/catalog.py`). All consumed by every later task.

- [ ] **Step 1: Check whether `tests/functional/test_bot_users.py` already exists**

Run: `ls tests/functional/test_bot_users.py 2>&1`
If it exists, read it first and append the new tests below into it (keeping its existing tests untouched). If it doesn't exist, create it fresh with just the new tests below.

- [ ] **Step 2: Write the failing tests**

Create/append to `tests/functional/test_bot_users.py`:

```python
@pytest.mark.asyncio
async def test_get_language_defaults_to_none() -> None:
    from app.services.bot_users import get_language, record_seen

    async with async_session_maker() as session:
        await record_seen(session, 9001, None)

    async with async_session_maker() as session:
        assert await get_language(session, 9001) is None


@pytest.mark.asyncio
async def test_set_language_round_trips() -> None:
    from app.services.bot_users import get_language, record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 9002, None)
        await set_language(session, 9002, "fa")

    async with async_session_maker() as session:
        assert await get_language(session, 9002) == "fa"


@pytest.mark.asyncio
async def test_set_language_on_unknown_telegram_id_is_a_no_op() -> None:
    from app.services.bot_users import get_language, set_language

    async with async_session_maker() as session:
        await set_language(session, 9999999, "fa")  # no BotUser row exists

    async with async_session_maker() as session:
        assert await get_language(session, 9999999) is None
```

(If `tests/functional/test_bot_users.py` is new, its header needs:
```python
from __future__ import annotations

import pytest

from app.db.session import async_session_maker
```
)

Create `tests/functional/test_i18n.py`:

```python
from __future__ import annotations

import logging

import pytest


def test_t_returns_english_text() -> None:
    from app.i18n.texts import t

    assert t("menu_buy", "en") == "🔑 Buy Subscription"


def test_t_returns_persian_text() -> None:
    from app.i18n.texts import t

    assert t("menu_buy", "fa") == "🔑 خرید اشتراک"


def test_t_interpolates_kwargs() -> None:
    from app.i18n.texts import t

    result = t("price_duration", "en", days=30)
    assert result == "Duration: 30 days"


def test_t_falls_back_to_english_for_unknown_language(caplog: pytest.LogCaptureFixture) -> None:
    from app.i18n.texts import t

    with caplog.at_level(logging.WARNING):
        result = t("menu_buy", "de")
    assert result == "🔑 Buy Subscription"
    assert "de" in caplog.text


def test_t_missing_key_returns_bare_key(caplog: pytest.LogCaptureFixture) -> None:
    from app.i18n.texts import t

    with caplog.at_level(logging.WARNING):
        result = t("this_key_does_not_exist", "en")
    assert result == "this_key_does_not_exist"
    assert "this_key_does_not_exist" in caplog.text


def test_t_format_mismatch_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    from app.i18n.texts import t

    with caplog.at_level(logging.WARNING):
        result = t("price_duration", "en")  # missing required {days} kwarg
    assert result == "Duration: {days} days"


def test_texts_key_sets_match_exactly_between_languages() -> None:
    from app.i18n.texts import TEXTS

    assert set(TEXTS["en"].keys()) == set(TEXTS["fa"].keys())
    assert len(TEXTS["en"]) == 83


def test_texts_format_placeholders_match_between_languages() -> None:
    import re

    from app.i18n.texts import TEXTS

    placeholder_re = re.compile(r"\{(\w+)\}")
    for key, en_text in TEXTS["en"].items():
        en_placeholders = set(placeholder_re.findall(en_text))
        fa_placeholders = set(placeholder_re.findall(TEXTS["fa"][key]))
        assert en_placeholders == fa_placeholders, f"placeholder mismatch for key {key!r}"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/functional/test_i18n.py tests/functional/test_bot_users.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.i18n'` and `ImportError: cannot import name 'get_language'`.

- [ ] **Step 4: Create the migration**

Create `alembic/versions/0009_bot_user_language.py`:

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

- [ ] **Step 5: Add the field to the model**

In `app/db/models/bot_user.py`, add one line after `is_blocked`:

```python
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
```

- [ ] **Step 6: Add `get_language`/`set_language` to `app/services/bot_users.py`**

Append to the end of `app/services/bot_users.py` (after the existing `list_bot_user_ids`):

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

- [ ] **Step 7: Create `app/i18n/__init__.py`**

```python
```

(empty file)

- [ ] **Step 8: Create `app/i18n/texts.py`**

```python
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_LANG = "en"

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

- [ ] **Step 9: Write the catalog display-name tests**

Append to `tests/functional/test_catalog.py`:

```python
@pytest.mark.asyncio
async def test_plan_display_name_translates_known_names() -> None:
    from app.services.catalog import plan_display_name

    async with async_session_maker() as session:
        plans = await list_plans(session)
    trial_plan = next(p for p in plans if p.category == "trial")

    assert plan_display_name(trial_plan, "en") == "Trial"
    assert plan_display_name(trial_plan, "fa") == "تست رایگان"


def test_plan_display_name_falls_back_to_raw_name_for_unknown_plan() -> None:
    from app.db.models.plan import Plan
    from app.services.catalog import plan_display_name

    fake_plan = Plan(name="Custom Weird Plan", category="scroll", duration_days=1, data_cap_mb=1, price_usd="1.00", group_name="x", sort_order=0)
    assert plan_display_name(fake_plan, "en") == "Custom Weird Plan"
    assert plan_display_name(fake_plan, "fa") == "Custom Weird Plan"


def test_category_display_name_translates_known_categories() -> None:
    from app.services.catalog import category_display_name

    assert category_display_name("scroll", "en") == "📜 Scroll"
    assert category_display_name("scroll", "fa") == "📜 اسکرول"
    assert category_display_name("stream", "en") == "🌊 Stream"


def test_category_display_name_falls_back_to_title_case_for_unknown_category() -> None:
    from app.services.catalog import category_display_name

    assert category_display_name("weird", "en") == "Weird"
```

(If `tests/functional/test_catalog.py` doesn't already import `list_plans`/`async_session_maker`/`pytest`, check its existing imports first and add only what's missing.)

- [ ] **Step 10: Run all new tests to verify they still fail correctly**

Run: `pytest tests/functional/test_i18n.py tests/functional/test_bot_users.py tests/functional/test_catalog.py -v -k "language or plan_display_name or category_display_name or i18n or TEXT"`
Expected: FAIL — `t`/`get_language`/`set_language`/`plan_display_name`/`category_display_name` not defined, migration not applied.

- [ ] **Step 11: Add `plan_display_name`/`category_display_name` to `app/services/catalog.py`**

Add near the top of `app/services/catalog.py` (after its existing imports) and at the end of the file:

```python
from app.i18n.texts import t
```

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

(`Plan` is already imported in `catalog.py` for `list_plans`/`get_plan` — no new import needed for it.)

- [ ] **Step 12: Run migration and full new test set**

Run: `alembic upgrade head` (or let the test suite's own `_migrate_test_database` fixture handle it — running the tests below re-runs `alembic upgrade head` automatically).
Run: `pytest tests/functional/test_i18n.py tests/functional/test_bot_users.py tests/functional/test_catalog.py -v`
Expected: PASS — all new tests green.

- [ ] **Step 13: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions (this task adds a nullable column and new pure functions — nothing existing calls them yet).

- [ ] **Step 14: Commit**

```bash
git add alembic/versions/0009_bot_user_language.py app/db/models/bot_user.py app/services/bot_users.py app/i18n/ app/services/catalog.py tests/functional/test_i18n.py tests/functional/test_bot_users.py tests/functional/test_catalog.py
git commit -m "feat: add BotUser.language, i18n infrastructure, and plan display-name helpers"
```

---

## Task 2: Language middleware, main-menu switching UI, and the test-default fixture

**Files:**
- Create: `app/bot/middlewares/language.py`, `app/bot/keyboards/language.py`
- Modify: `app/bot/handlers/users.py`, `app/bot/keyboards/menus.py`, `app/bot/handlers/fallback.py`, `app/main.py`
- Modify: `tests/conftest.py`
- Test: `tests/functional/test_language_flow.py` (new), `tests/functional/test_start_and_menu.py` (append)

**Interfaces:**
- Consumes: `get_language`/`set_language` (Task 1), `t`/`CHOOSE_LANGUAGE_TEXT` (Task 1).
- Produces: `data["lang"]` available as an injected `lang: str` parameter to every handler downstream of `LanguageMiddleware` — every later task relies on declaring `lang: str` in its handler signatures. `main_menu(*, is_admin: bool, lang: str)`, `send_main_menu(target: Message, *, lang: str)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_language_flow.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_new_user_sees_language_chooser_instead_of_main_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Undoes the autouse test-default fixture for this one test, to
    verify the real production gating behavior - a brand-new customer
    (language still unset) must see the chooser, not the main menu."""
    from app.services.bot_users import get_language
    import app.bot.middlewares.language as language_mw

    monkeypatch.setattr(language_mw, "get_language", get_language)

    await dispatcher.feed_update(bot, make_message_update(20001, "/start"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert "Please choose your language" in sent[0][1]["text"]
    buttons = [b["text"] for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🇮🇷 فارسی" in buttons
    assert "🇬🇧 English" in buttons


@pytest.mark.asyncio
async def test_choosing_persian_sets_language_and_shows_persian_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.bot_users import get_language as real_get_language
    import app.bot.middlewares.language as language_mw

    monkeypatch.setattr(language_mw, "get_language", real_get_language)

    await dispatcher.feed_update(bot, make_message_update(20002, "/start"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(20002, "lang:set:fa"))

    async with async_session_maker() as session:
        assert await real_get_language(session, 20002) == "fa"

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert any("خوش آمدید" in c[1]["text"] for c in edited)


@pytest.mark.asyncio
async def test_choosing_english_sets_language_and_shows_english_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.bot_users import get_language as real_get_language
    import app.bot.middlewares.language as language_mw

    monkeypatch.setattr(language_mw, "get_language", real_get_language)

    await dispatcher.feed_update(bot, make_message_update(20003, "/start"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(20003, "lang:set:en"))

    async with async_session_maker() as session:
        assert await real_get_language(session, 20003) == "en"

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert any("Welcome to Homeland" in c[1]["text"] for c in edited)


@pytest.mark.asyncio
async def test_language_button_on_main_menu_reruns_chooser(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(20004, "menu:language"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Please choose your language" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_changing_language_later_updates_stored_value(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import get_language

    await dispatcher.feed_update(bot, make_callback_update(20005, "lang:set:fa"))
    await dispatcher.feed_update(bot, make_callback_update(20005, "menu:language"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(20005, "lang:set:en"))

    async with async_session_maker() as session:
        assert await get_language(session, 20005) == "en"
```

Append to `tests/functional/test_start_and_menu.py`:

```python
@pytest.mark.asyncio
async def test_main_menu_includes_language_button(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_message_update(999, "/start")
    await dispatcher.feed_update(bot, update)

    _, data = [call for call in fake_session.calls if call[0] == "sendMessage"][0]
    buttons = [btn["text"] for row in data["reply_markup"]["inline_keyboard"] for btn in row]
    assert "🌐 Language" in buttons
```

(Note: `test_start_shows_english_main_menu`'s existing exact-button-list assertion will need `"🌐 Language"` added to its expected list in this same step, in the position after `"☎️ Support"` — update that existing assertion in place rather than leaving it to fail.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_language_flow.py tests/functional/test_start_and_menu.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bot.middlewares.language'`, and the existing button-list test now fails on the missing `"🌐 Language"` entry.

- [ ] **Step 3: Create `app/bot/keyboards/language.py`**

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

- [ ] **Step 4: Create `app/bot/middlewares/language.py`**

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

- [ ] **Step 5: Add the test-default fixture to `tests/conftest.py`**

Add this **before** any test in this task runs — it must land before Step 6's dispatcher wiring is exercised by any test. Add near the other `autouse=True` fixtures (alongside `_reset_ibsng`/`_reset_dispatcher_fsm_storage`):

```python
@pytest_asyncio.fixture(autouse=True)
async def _default_test_language(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None, None]:
    """LanguageMiddleware gates every update behind BotUser.language being
    set - a fresh BotUser row (the default for every test unless a test
    seeds otherwise) would make every existing dispatcher-driven test in
    the whole suite hit the language chooser instead of its real target.
    Rather than retrofit hundreds of call sites, default language
    resolution to "en" here, in the test environment only - matching this
    project's ibsng_server-fixture precedent of faking cross-cutting
    external state instead of touching production code. A test that needs
    to exercise the REAL chooser-gating behavior re-monkeypatches the
    unwrapped get_language back on top of this, within its own body, using
    the same `monkeypatch` fixture instance (a later setattr call safely
    overwrites this one for the rest of that single test)."""
    import app.bot.middlewares.language as language_mw

    original_get_language = language_mw.get_language

    async def _get_language_default_en(session: Any, telegram_id: int) -> str:
        result = await original_get_language(session, telegram_id)
        return result if result is not None else "en"

    monkeypatch.setattr(language_mw, "get_language", _get_language_default_en)
    yield
```

(`monkeypatch` is pytest's built-in fixture, no import needed beyond `pytest` which `conftest.py` already imports. `AsyncGenerator`/`Any` are already imported at the top of `conftest.py`.)

- [ ] **Step 6: Register `LanguageMiddleware` in `app/main.py`**

In `build_dispatcher`, add the import and register it between `UserTrackingMiddleware` and `BlockedUserMiddleware`:

```python
from app.bot.middlewares.language import LanguageMiddleware
```

```python
    dp.update.outer_middleware(PrivateChatOnlyMiddleware())
    dp.update.outer_middleware(UserTrackingMiddleware())
    dp.update.outer_middleware(LanguageMiddleware())
    dp.update.outer_middleware(BlockedUserMiddleware())
    dp.update.outer_middleware(MandatoryChannelMiddleware())
```

- [ ] **Step 7: Run the FULL existing suite before writing anything else in this task**

Run: `pytest tests/ -v`
Expected: PASS — every pre-existing test in the whole project must still be green with the fixture from Step 5 in place and the middleware registered. If anything fails here, stop and fix the fixture before proceeding to Step 8 — this is the task's primary acceptance bar, not an afterthought.

- [ ] **Step 8: Update `app/bot/keyboards/menus.py`'s `main_menu()`**

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t


def main_menu(*, is_admin: bool, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []

    builder.button(text=t("menu_buy", lang), callback_data="menu:buy", style="success")
    builder.button(text=t("menu_renew", lang), callback_data="menu:renew", style="success")
    builder.button(text=t("menu_trial", lang), callback_data="menu:trial", style="primary")
    builder.button(text=t("menu_myservices", lang), callback_data="menu:myservices", style="primary")
    builder.button(text=t("menu_tutorials", lang), callback_data="menu:tutorials", style="danger")
    builder.button(text=t("menu_support", lang), callback_data="menu:support", style="danger")
    builder.button(text=t("menu_language", lang), callback_data="menu:language")
    sizes += [2, 2, 2, 1]

    if is_admin:
        builder.button(text="🛠 Admin Panel", callback_data="adm:root")
        sizes.append(1)

    builder.adjust(*sizes)
    return builder.as_markup()


def support_keyboard(url: str | None, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if url:
        builder.button(text=t("contact_support_button", lang), url=url)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

("🛠 Admin Panel" stays a bare string, not a `t()` call — it's the one button on this otherwise-customer-facing menu that belongs to the admin-facing surface, per the spec's boundary; translating it would put an admin-only concept inside the customer i18n dict.)

- [ ] **Step 9: Update `app/bot/handlers/users.py`**

Full new content:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.language import language_choice_keyboard
from app.bot.keyboards.menus import main_menu, support_keyboard
from app.config import get_settings
from app.db.session import async_session_maker
from app.i18n.texts import CHOOSE_LANGUAGE_TEXT, t
from app.services.admin_users import has_level
from app.services.app_config import get_config
from app.services.bot_users import set_language

router = Router(name="users")

PLACEHOLDER_TEXT = "🚧 This feature is coming soon."

_PLACEHOLDER_CALLBACKS = {
    "menu:tutorials",
}


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


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


@router.callback_query(F.data.in_(_PLACEHOLDER_CALLBACKS))
async def placeholder_cb(callback: CallbackQuery, lang: str) -> None:
    await callback.answer(t("placeholder_coming_soon", lang), show_alert=True)


@router.callback_query(F.data == "menu:support")
async def menu_support_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        support_username = await get_config(session, "support_username")
    if not support_username:
        support_username = get_settings().support_username

    url = f"https://t.me/{support_username.lstrip('@')}" if support_username else None
    text = t("support_heading", lang) if url else t("support_not_configured", lang)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=support_keyboard(url, lang))
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

(`WELCOME_TEXT`, `_SUPPORT_TEXT`, `_SUPPORT_NOT_CONFIGURED_TEXT` module constants are removed — replaced by `t()` calls. `PLACEHOLDER_TEXT` module constant is kept as-is per the existing test suite's likely reference to it, but `placeholder_cb` itself now uses `t("placeholder_coming_soon", lang)` instead.)

- [ ] **Step 10: Update `app/bot/handlers/fallback.py`**

```python
from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.handlers.users import send_main_menu

router = Router(name="fallback")


@router.message()
async def fallback_to_main_menu(message: Message, state: FSMContext, lang: str) -> None:
    """Registered last in main.py, after every other router - only ever
    reached once no command/state-specific handler claimed the message
    first. Shows the main menu unless the user has an FSM state in
    progress, in which case some state-specific handler already had
    first refusal and this isn't the place to guess at what they meant."""
    if await state.get_state() is not None:
        return
    await send_main_menu(message, lang=lang)
```

- [ ] **Step 11: Fix the existing exact-button-list assertion**

In `tests/functional/test_start_and_menu.py`'s `test_start_shows_english_main_menu`, update the expected buttons list to include the new Language button after Support:

```python
    assert buttons == [
        "🔑 Buy Subscription",
        "♻️ Renew Service",
        "🎁 Free Trial",
        "🛍 My Services",
        "📚 Tutorials",
        "☎️ Support",
        "🌐 Language",
    ]
```

- [ ] **Step 12: Run this task's new tests**

Run: `pytest tests/functional/test_language_flow.py tests/functional/test_start_and_menu.py -v`
Expected: PASS.

- [ ] **Step 13: Run the full suite again**

Run: `pytest tests/ -v`
Expected: PASS, no regressions anywhere (Support's `support_keyboard` signature change is the one other call-site risk — confirm nothing besides `menu_support_cb` calls it).

- [ ] **Step 14: Commit**

```bash
git add app/bot/middlewares/language.py app/bot/keyboards/language.py app/bot/handlers/users.py app/bot/keyboards/menus.py app/bot/handlers/fallback.py app/main.py tests/conftest.py tests/functional/test_language_flow.py tests/functional/test_start_and_menu.py
git commit -m "feat: add language selection middleware and main-menu switching UI"
```

---

## Task 3: trial.py + trial keyboard + tutorial_delivery.py

**Files:**
- Modify: `app/bot/handlers/trial.py`, `app/bot/keyboards/trial.py`, `app/services/tutorial_delivery.py`
- Test: `tests/functional/test_trial_flow.py` (append)

**Interfaces:**
- Consumes: `t` (Task 1), `lang: str` injected parameter (Task 2).
- Produces: `back_to_menu_keyboard(lang: str = "en")` (default — consumed without the explicit kwarg by `myservices.py`/`buy.py`/`renew.py` until their own tasks land); `deliver_setup(..., lang: str = "en")` (default — consumed without the explicit kwarg by `myservices.py` until Task 4 lands).

- [ ] **Step 1: Write the failing tests**

Append to `tests/functional/test_trial_flow.py`:

```python
@pytest.mark.asyncio
async def test_trial_entry_shows_persian_confirm_for_persian_user(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 820, None)
        await set_language(session, 820, "fa")

    await dispatcher.feed_update(bot, make_callback_update(820, "menu:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "تست رایگان" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_trial_entry_shows_already_used_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=821, ibsng_username="hl.faused1", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await record_seen(session, 821, None)
        await set_language(session, 821, "fa")
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(821, "menu:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "قبلاً" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_trial_ready_credentials_render_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 822, None)
        await set_language(session, 822, "fa")

    await dispatcher.feed_update(bot, make_callback_update(822, "trial:confirm"))
    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(822, f"trial:protocol:{openvpn_id}"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("تست رایگان شما آماده است" in c[1]["text"] for c in sent)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_trial_flow.py -v -k persian`
Expected: FAIL — trial screens still render English regardless of stored language.

- [ ] **Step 3: Update `app/bot/keyboards/trial.py`**

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.i18n.texts import t


def trial_confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("confirm_button", lang), callback_data="trial:confirm", style="success")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def trial_protocol_keyboard(protocols: list[TutorialProtocol], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"trial:protocol:{protocol.id}")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def trial_platform_keyboard(platforms: list[TutorialPlatform], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"trial:platform:{platform.id}")
    builder.button(text=t("back_button", lang), callback_data="trial:back_to_protocol")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
```

(`back_to_menu_keyboard`'s `lang: str = "en"` default is deliberate — `myservices.py`/`buy.py`/`renew.py` still call it with no argument until their own tasks land; per Global Constraints, this is a temporary cross-task compatibility default, not a permanent design choice for this function's callers within `trial.py` itself, which always pass `lang` explicitly below.)

- [ ] **Step 4: Update `app/services/tutorial_delivery.py`**

Full new content:

```python
# app/services/tutorial_delivery.py
from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.i18n.texts import t
from app.services.app_config import get_config
from app.services.tutorials import find_matching_profile, get_guide, is_protocol_valid_for_platform, list_platforms

_MEDIA_SENDERS = {"photo": "send_photo", "document": "send_document", "video": "send_video"}

#: Platform segment of a download-link AppConfig key for a link that
#: applies to every platform ("Generic (any platform)" in the admin flow).
GENERIC_PLATFORM_KEY = "any"


def download_link_key(*, protocol_label: str, platform_label: str | None) -> str:
    """The one place the `download_link:{protocol}:{platform}` AppConfig
    key format is spelled out - the admin flow writes through it and
    deliver_setup reads through it, so the two can't drift (they already
    did once: the admin's generic `:any` key was written but never read)."""
    platform_key = platform_label.strip().lower() if platform_label is not None else GENERIC_PLATFORM_KEY
    return f"download_link:{protocol_label.strip().lower()}:{platform_key}"


async def _send_media_or_text(bot: Bot, telegram_id: int, *, file_id: str | None, file_type: str | None, text: str | None, fallback_prefix: str) -> None:
    if file_id is not None and file_type is not None:
        sender = getattr(bot, _MEDIA_SENDERS.get(file_type, "send_document"))
        await sender(telegram_id, file_id, caption=text or None)
        return
    if text is not None:
        await bot.send_message(telegram_id, f"{fallback_prefix}\n\n{text}")


async def deliver_setup(
    bot: Bot, telegram_id: int, session: AsyncSession, *, protocol_id: int, platform_id: int | None, lang: str = "en",
) -> tuple[bool, int | None]:
    """Shared by the trial flow now, Buy/Renew later. Sends the OpenVPN
    profile, the tutorial guide, and any configured download link - it
    does NOT send account credentials, since not every future caller
    will want the same closing message (and the caller, not this
    function, is the one that actually has the username/password in
    scope). Returns (delivered, guide_message_id) - delivered=False
    means the caller must NOT send its own credentials message either
    (currently only the Android+L2TP compatibility gate triggers this).
    `lang` defaults to "en" so a not-yet-migrated caller (see the
    bilingual-flows plan's Task 4) keeps working correctly until it
    starts passing lang explicitly."""
    protocol = await session.get(TutorialProtocol, protocol_id)
    platform = await session.get(TutorialPlatform, platform_id) if platform_id is not None else None

    if platform is not None and not is_protocol_valid_for_platform(platform.label, protocol.label):
        await bot.send_message(telegram_id, t("android_l2tp_unsupported", lang))
        return False, None

    if protocol.label.strip().lower() == "openvpn":
        profile = await find_matching_profile(session, platform_id=platform_id)
        if profile is not None:
            await _send_media_or_text(
                bot, telegram_id, file_id=profile.file_id, file_type=profile.file_type,
                text=profile.text, fallback_prefix=t("connection_profile_prefix", lang, name=profile.name),
            )

    guide = await get_guide(session, platform_id=platform_id, protocol_id=protocol_id)
    guide_message_id: int | None = None
    if guide is not None and (guide.media_file_id is not None or guide.body_html is not None):
        if guide.media_file_id is not None and guide.media_type is not None:
            sender = getattr(bot, _MEDIA_SENDERS.get(guide.media_type, "send_document"))
            message = await sender(telegram_id, guide.media_file_id, caption=guide.body_html or None)
        else:
            message = await bot.send_message(telegram_id, guide.body_html or "")
        guide_message_id = message.message_id
    else:
        await bot.send_message(telegram_id, t("guide_not_ready", lang))

    # The admin flow's "Generic (any platform)" option writes the
    # :any-suffixed key, so both branches below have to read it or an
    # admin's generic link is written but never shown to anyone.
    generic_link = await get_config(session, download_link_key(protocol_label=protocol.label, platform_label=None))
    if platform is not None:
        link = await get_config(session, download_link_key(protocol_label=protocol.label, platform_label=platform.label))
        link = link or generic_link
        if link:
            await bot.send_message(telegram_id, f"{t('download_link_prefix', lang)}\n{link}")
    else:
        # No platform was picked (OpenVPN's shared-guide path) - show every
        # configured platform's link at once so the user can pick their own.
        links = []
        for candidate_platform in await list_platforms(session):
            candidate_link = await get_config(
                session, download_link_key(protocol_label=protocol.label, platform_label=candidate_platform.label)
            )
            if candidate_link:
                links.append(f"{candidate_platform.label}: {candidate_link}")
        if generic_link:
            links.append(f"{t('any_platform_label', lang)} {generic_link}")
        if links:
            await bot.send_message(telegram_id, t("download_openvpn_links_heading", lang) + "\n" + "\n".join(links))

    return True, guide_message_id
```

- [ ] **Step 5: Update `app/bot/handlers/trial.py`**

Full new content:

```python
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.bot.keyboards.trial import back_to_menu_keyboard, trial_confirm_keyboard, trial_platform_keyboard, trial_protocol_keyboard
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import list_plans
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols
from app.services.vpn_users import (
    TrialAlreadyUsedError,
    VPNUsernameTakenError,
    create_vpn_user,
    generate_vpn_credentials,
    has_used_trial,
)

router = Router(name="trial")

logger = logging.getLogger(__name__)

_MAX_CREATE_ATTEMPTS = 3


async def _send_trial_credentials(bot: Bot, telegram_id: int, lang: str) -> None:
    """deliver_setup (Task 3) deliberately does NOT send the account's
    username/password - it's a generic (platform, protocol) -> content
    function reused later by Buy/Renew, which won't always want the
    same trial-specific closing message. The credentials themselves were
    generated back in trial_confirm_cb, a separate callback invocation
    with nothing carried forward (no FSM state, by design - see the
    spec's rationale for not putting a password in callback_data), so
    they're looked up fresh here: the just-created VPNUser row gives the
    username, and IBSngClient.get_user_password re-reads the password
    IBSng already has stored for it (same accessor AloBot's own renew
    flow uses to re-show an existing password)."""
    async with async_session_maker() as session:
        vpn_user = (
            await session.execute(
                select(VPNUser)
                .where(VPNUser.telegram_id == telegram_id, VPNUser.is_trial.is_(True))
                .order_by(VPNUser.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if vpn_user is None:
        return

    try:
        async with IBSngClient() as client:
            password = await client.get_user_password(username=vpn_user.ibsng_username)

        if password is None:
            # get_user_password returns None when IBSng has no such user,
            # or when its getUserInfo response carries no stored
            # normal_password - either way there is nothing to show, and
            # rendering it would print a literal "None" as the password.
            logger.error(
                "IBSng returned no password for just-created trial account %r (telegram_id=%s)",
                vpn_user.ibsng_username,
                telegram_id,
            )
            await bot.send_message(telegram_id, t("trial_credentials_unavailable", lang))
            return

        await bot.send_message(
            telegram_id, t("trial_ready", lang, username=vpn_user.ibsng_username, password=password)
        )
    except Exception:
        # The account exists but we couldn't hand over its credentials.
        # Failing silently here would leave the user with a delivered
        # guide, a real trial account, and no way to log in - so tell
        # them explicitly to contact support (there is no self-service
        # "show me my credentials again" flow yet; that belongs to the
        # My Services plan).
        logger.exception(
            "Could not deliver trial credentials for %r (telegram_id=%s)",
            vpn_user.ibsng_username,
            telegram_id,
        )
        try:
            await bot.send_message(telegram_id, t("trial_credentials_unavailable", lang))
        except Exception:
            logger.exception("Could not deliver the credentials-unavailable message to telegram_id=%s", telegram_id)


@router.callback_query(F.data == "menu:trial")
async def trial_entry_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        already_used = await has_used_trial(session, callback.from_user.id)

    if callback.message is None:
        await callback.answer()
        return
    if already_used:
        await callback.message.edit_text(t("trial_already_used", lang), reply_markup=back_to_menu_keyboard(lang))
    else:
        await callback.message.edit_text(t("trial_confirm_prompt", lang), reply_markup=trial_confirm_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data == "trial:confirm")
async def trial_confirm_cb(callback: CallbackQuery, lang: str) -> None:
    telegram_id = callback.from_user.id

    # "trial:confirm" is a bare callback_data string: an old message's
    # button still works, so this callback can arrive without ever
    # passing through trial_entry_cb's eligibility check. Re-check here
    # rather than trusting the path the user took to get here.
    async with async_session_maker() as session:
        if await has_used_trial(session, telegram_id):
            if callback.message is not None:
                await callback.message.edit_text(t("trial_already_used", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

    async with async_session_maker() as session:
        trial_plans = await list_plans(session, category="trial")
    trial_plan = trial_plans[0]

    vpn_user = None
    last_error: str | None = None
    for _attempt in range(_MAX_CREATE_ATTEMPTS):
        username, password = generate_vpn_credentials()
        async with async_session_maker() as session, IBSngClient() as client:
            try:
                vpn_user = await create_vpn_user(
                    session, client,
                    telegram_id=telegram_id, username=username, password=password,
                    group_name=trial_plan.group_name, data_cap_mb=trial_plan.data_cap_mb,
                    plan_id=trial_plan.id, is_trial=True,
                )
                break
            except TrialAlreadyUsedError:
                # Retrying is pointless (and, before the pre-check landed,
                # actively harmful): the blocker is the telegram_id, not
                # the generated username, so a fresh username can never
                # make the next attempt succeed.
                last_error = "trial_used"
                break
            except (VPNUsernameTakenError, IBSngUserExistsError):
                last_error = "taken"
                continue
            except IBSngError:
                last_error = "ibsng"
                break

    if vpn_user is None:
        if callback.message is not None:
            # Only "trial_used" actually means the trial is spent. Both
            # "taken" (every attempt lost a genuine username collision)
            # and "ibsng" (a real IBSng failure) are transient - telling
            # an eligible user their trial was "already used" in those
            # cases would be flatly wrong.
            text = t("trial_already_used", lang) if last_error == "trial_used" else t("trial_create_failed", lang)
            await callback.message.edit_text(text, reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()
        return

    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(t("protocol_prompt", lang), reply_markup=trial_protocol_keyboard(protocols, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("trial:protocol:"))
async def trial_protocol_cb(callback: CallbackQuery, lang: str) -> None:
    protocol_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)

    if protocol is not None and protocol.label.strip().lower() == "openvpn":
        async with async_session_maker() as session:
            delivered, _ = await deliver_setup(callback.bot, callback.from_user.id, session, protocol_id=protocol_id, platform_id=None, lang=lang)
        if delivered:
            await _send_trial_credentials(callback.bot, callback.from_user.id, lang)
        await callback.answer()
        return

    async with async_session_maker() as session:
        platforms = await list_platforms(session)
    if callback.message is not None:
        await callback.message.edit_text(
            t("platform_prompt", lang),
            reply_markup=trial_platform_keyboard(platforms, lang),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("trial:platform:"))
async def trial_platform_cb(callback: CallbackQuery, lang: str) -> None:
    platform_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    l2tp = next(p for p in protocols if p.label.strip().lower() == "l2tp")

    async with async_session_maker() as session:
        delivered, _ = await deliver_setup(callback.bot, callback.from_user.id, session, protocol_id=l2tp.id, platform_id=platform_id, lang=lang)
    if delivered:
        await _send_trial_credentials(callback.bot, callback.from_user.id, lang)
    await callback.answer()


@router.callback_query(F.data == "trial:back_to_protocol")
async def trial_back_to_protocol_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(t("protocol_prompt", lang), reply_markup=trial_protocol_keyboard(protocols, lang))
    await callback.answer()
```

- [ ] **Step 6: Run this task's tests**

Run: `pytest tests/functional/test_trial_flow.py -v`
Expected: PASS — every existing English-path test still passes (via Task 2's autouse fixture defaulting to `"en"`), and the 3 new Persian-path tests pass too.

- [ ] **Step 7: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions. (`myservices.py` still calls `deliver_setup`/`back_to_menu_keyboard` with no `lang` argument at this point — both defaults keep it rendering English exactly as before.)

- [ ] **Step 8: Commit**

```bash
git add app/bot/handlers/trial.py app/bot/keyboards/trial.py app/services/tutorial_delivery.py tests/functional/test_trial_flow.py
git commit -m "feat: migrate trial flow and tutorial delivery to bilingual text"
```

---

## Task 4: myservices.py + myservices keyboard

**Files:**
- Modify: `app/bot/handlers/myservices.py`, `app/bot/keyboards/myservices.py`
- Test: `tests/functional/test_myservices_flow.py` (append)

**Interfaces:**
- Consumes: `t` (Task 1), `lang: str` injected parameter (Task 2), `back_to_menu_keyboard(lang: str = "en")` and `deliver_setup(..., lang: str = "en")` (Task 3) — this task starts passing `lang=lang` to both explicitly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/functional/test_myservices_flow.py`:

```python
@pytest.mark.asyncio
async def test_myservices_empty_state_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 710, None)
        await set_language(session, 710, "fa")

    await dispatcher.feed_update(bot, make_callback_update(710, "menu:myservices"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "سرویسی ندارید" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🎁 تست رایگان" in buttons


@pytest.mark.asyncio
async def test_myservices_detail_status_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    import datetime as dt

    from app.services.bot_users import record_seen, set_language

    telegram_id = 711
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(service.ibsng_username, "nearest_exp_date", future)

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "وضعیت: ✅ فعال" in edited[0][1]["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_myservices_flow.py -v -k persian`
Expected: FAIL — myservices screens still render English regardless of stored language.

- [ ] **Step 3: Update `app/bot/keyboards/myservices.py`**

Full new content:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.i18n.texts import t

_STATUS_KEYS = {
    "active": "status_active",
    "expired": "status_expired",
    "pending": "status_pending",
    "unknown": "status_unknown",
}


def myservices_empty_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("menu_buy", lang), callback_data="menu:buy", style="success")
    builder.button(text=t("menu_trial", lang), callback_data="menu:trial", style="primary")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def myservices_list_keyboard(rows: list[tuple[VPNUser, Plan | None, str]], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan, status in rows:
        name = plan.name if plan is not None else vpn_user.ibsng_group
        status_text = t(_STATUS_KEYS.get(status, "status_unknown"), lang)
        builder.button(
            text=f"{name} — {status_text}",
            callback_data=f"myservices:view:{vpn_user.id}",
        )
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def myservices_detail_keyboard(vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("resend_setup_button", lang), callback_data=f"myservices:resend:{vpn_user_id}")
    builder.button(text=t("back_to_list_button", lang), callback_data="menu:myservices")
    builder.adjust(1)
    return builder.as_markup()


def myservices_protocol_keyboard(protocols: list[TutorialProtocol], vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"myservices:resend:{vpn_user_id}:protocol:{protocol.id}")
    builder.button(text=t("back_to_service_button", lang), callback_data=f"myservices:view:{vpn_user_id}")
    builder.adjust(2, 1)
    return builder.as_markup()


def myservices_platform_keyboard(
    platforms: list[TutorialPlatform], vpn_user_id: int, protocol_id: int, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(
            text=platform.label,
            callback_data=f"myservices:resend:{vpn_user_id}:platform:{protocol_id}:{platform.id}",
        )
    builder.button(text=t("back_button", lang), callback_data=f"myservices:resend:{vpn_user_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
```

(`_STATUS_BADGE` is renamed `_STATUS_KEYS` and now maps to i18n keys, not literal text — `status_text` computed at call time from `t()` instead of a dict of raw strings.)

- [ ] **Step 4: Update `app/bot/handlers/myservices.py`**

Full new content:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.myservices import (
    myservices_detail_keyboard,
    myservices_empty_keyboard,
    myservices_list_keyboard,
    myservices_platform_keyboard,
    myservices_protocol_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import get_plan
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols
from app.services.vpn_users import get_owned_vpn_user, get_service_status, list_services_with_status

router = Router(name="myservices")


@router.callback_query(F.data == "menu:myservices")
async def myservices_list_cb(callback: CallbackQuery, lang: str) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session, IBSngClient() as client:
        rows = await list_services_with_status(session, client, telegram_id)

    if not rows:
        if callback.message is not None:
            await callback.message.edit_text(t("myservices_empty", lang), reply_markup=myservices_empty_keyboard(lang))
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(t("myservices_heading", lang), reply_markup=myservices_list_keyboard(rows, lang))
    await callback.answer()


async def _detail_text(session: AsyncSession, client: IBSngClient, vpn_user: VPNUser, lang: str) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    name = plan.name if plan is not None else vpn_user.ibsng_group
    status, expiry = await get_service_status(client, vpn_user.ibsng_username)

    if status == "active":
        status_line = t("status_line_active", lang, date=f"{expiry:%Y-%m-%d %H:%M}")
    elif status == "expired":
        status_line = t("status_line_expired", lang, date=f"{expiry:%Y-%m-%d %H:%M}")
    elif status == "pending":
        status_line = t("status_line_pending", lang)
    else:
        status_line = t("status_line_unknown", lang)

    # Mirrors app/bot/handlers/trial.py's _send_trial_credentials: a
    # transient IBSng failure fetching the password must never crash the
    # screen showing it - get_service_status above is already immune to
    # this (it never raises), but get_user_password has no such
    # guarantee, so it needs its own try/except here.
    try:
        password = await client.get_user_password(username=vpn_user.ibsng_username)
    except IBSngError:
        password = None
    password_line = (
        f"Password: <code>{password}</code>" if password is not None else t("password_unavailable", lang)
    )

    return (
        f"🔑 <b>{name}</b>\n"
        f"{status_line}\n\n"
        f"Username: <code>{vpn_user.ibsng_username}</code>\n"
        f"{password_line}"
    )


@router.callback_query(F.data.startswith("myservices:view:"))
async def myservices_view_cb(callback: CallbackQuery, lang: str) -> None:
    vpn_user_id = int(callback.data.split(":")[-1])
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            if callback.message is not None:
                await callback.message.edit_text(t("myservices_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        async with IBSngClient() as client:
            text = await _detail_text(session, client, vpn_user, lang)

    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user.id, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("myservices:resend:"))
async def myservices_resend_cb(callback: CallbackQuery, lang: str) -> None:
    # callback_data is attacker-controlled (see the design spec's threat
    # model - ownership is checked below precisely because of this), so
    # every int() parse of a segment here is guarded: a malformed or
    # missing segment must degrade to the same not-found screen used for
    # an unowned/nonexistent service, never raise ValueError/IndexError.
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    async def _not_found() -> None:
        if callback.message is not None:
            await callback.message.edit_text(t("myservices_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()

    try:
        vpn_user_id = int(parts[2])
    except (IndexError, ValueError):
        await _not_found()
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found()
            return

        if len(parts) == 3:
            # myservices:resend:<id> - entry point, show the protocol picker.
            protocols = await list_protocols(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    t("protocol_prompt", lang), reply_markup=myservices_protocol_keyboard(protocols, vpn_user_id, lang)
                )
            await callback.answer()
            return

        if parts[3] == "protocol":
            try:
                protocol_id = int(parts[4])
            except (IndexError, ValueError):
                await _not_found()
                return

            protocol = await session.get(TutorialProtocol, protocol_id)
            if protocol is not None and protocol.label.strip().lower() == "openvpn":
                delivered, _ = await deliver_setup(
                    callback.bot, telegram_id, session, protocol_id=protocol_id, platform_id=None, lang=lang
                )
                text = t("resent_confirmation", lang) if delivered else t("resend_blocked", lang)
                if callback.message is not None:
                    await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user_id, lang))
                await callback.answer()
                return

            platforms = await list_platforms(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    t("platform_prompt", lang),
                    reply_markup=myservices_platform_keyboard(platforms, vpn_user_id, protocol_id, lang),
                )
            await callback.answer()
            return

        # parts[3] == "platform": myservices:resend:<id>:platform:<protocol_id>:<platform_id>
        try:
            protocol_id = int(parts[4])
            platform_id = int(parts[5])
        except (IndexError, ValueError):
            await _not_found()
            return

        # deliver_setup does `protocol = await session.get(...)` and then
        # unconditionally accesses `protocol.label` - a syntactically valid
        # but nonexistent protocol_id would raise AttributeError there, so
        # guard the call site here (mirroring the "protocol" branch above,
        # which already does its own existence check before touching
        # `.label`) rather than calling into shared infrastructure blind.
        protocol = await session.get(TutorialProtocol, protocol_id)
        if protocol is None:
            await _not_found()
            return

        delivered, _ = await deliver_setup(
            callback.bot, telegram_id, session, protocol_id=protocol_id, platform_id=platform_id, lang=lang
        )
        text = t("resent_confirmation", lang) if delivered else t("resend_blocked", lang)
        if callback.message is not None:
            await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user_id, lang))
        await callback.answer()
```

(`Username:`/`Password:` labels inside `_detail_text` stay a mix — `password_unavailable`'s key already includes the full "Password: unavailable — contact support" phrase per Task 1's dict, while the two-line "Username: `<code>`.../Password: `<code>`..." labels for the success case use bare English words matching this existing function's pre-migration style; if you want `Username:` translated too, that's a spec follow-up, not silently added here — the spec's key table (§7) has no `username_label` key, and inventing one outside the reviewed spec would drift from what was approved.)

- [ ] **Step 5: Run this task's tests**

Run: `pytest tests/functional/test_myservices_flow.py -v`
Expected: PASS — all existing tests plus the 2 new Persian-path tests.

- [ ] **Step 6: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add app/bot/handlers/myservices.py app/bot/keyboards/myservices.py tests/functional/test_myservices_flow.py
git commit -m "feat: migrate My Services flow to bilingual text"
```

---

## Task 5: buy.py + buy keyboard

**Files:**
- Modify: `app/bot/handlers/buy.py`, `app/bot/keyboards/buy.py`
- Test: `tests/functional/test_buy_flow.py` (append)

**Interfaces:**
- Consumes: `t`, `plan_display_name`, `category_display_name` (Task 1), `lang: str` injected (Task 2), `back_to_menu_keyboard(lang: str = "en")` (Task 3, now called with explicit `lang=lang`).
- Produces: `payment_link_keyboard(invoice_url: str, lang: str = "en")` (default — consumed without the explicit kwarg by `renew.py` until Task 6 lands).

- [ ] **Step 1: Write the failing tests**

Append to `tests/functional/test_buy_flow.py`:

```python
@pytest.mark.asyncio
async def test_buy_category_screen_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 830, None)
        await set_language(session, 830, "fa")

    await dispatcher.feed_update(bot, make_callback_update(830, "menu:buy"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "خرید اشتراک" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 اسکرول" in buttons


@pytest.mark.asyncio
async def test_buy_price_summary_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.bot_users import record_seen, set_language

    plan_id = next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll" and p["name"] == "1 Month")

    async with async_session_maker() as session:
        await record_seen(session, 831, None)
        await set_language(session, 831, "fa")

    await dispatcher.feed_update(bot, make_callback_update(831, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "مدت:" in edited[0][1]["text"]
    assert "قیمت:" in edited[0][1]["text"]
```

(Check `tests/functional/test_buy_flow.py`'s existing imports/fixtures first — reuse whatever helper it already has for looking up a seeded plan id, matching its established pattern rather than introducing a new one.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_buy_flow.py -v -k persian`
Expected: FAIL — buy screens still render English regardless of stored language.

- [ ] **Step 3: Update `app/bot/keyboards/buy.py`**

Full new content:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.i18n.texts import t
from app.services.catalog import category_display_name, format_data_cap, format_price_usd, plan_display_name


def buy_category_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=category_display_name("scroll", lang), callback_data="buy:category:scroll")
    builder.button(text=category_display_name("stream", lang), callback_data="buy:category:stream")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def buy_plan_keyboard(plans: list[Plan], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan_display_name(plan, lang)} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb)})",
            callback_data=f"buy:plan:{plan.id}",
        )
    builder.button(text=t("back_button", lang), callback_data="menu:buy")
    builder.adjust(1)
    return builder.as_markup()


def buy_price_summary_keyboard(plan_id: int, category: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("pay_with_crypto_button", lang), callback_data=f"buy:confirm:{plan_id}", style="success")
    builder.button(text=t("back_button", lang), callback_data=f"buy:category:{category}")
    builder.adjust(1)
    return builder.as_markup()


def payment_link_keyboard(invoice_url: str, lang: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("open_payment_page_button", lang), url=invoice_url)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

(`payment_link_keyboard`'s `lang: str = "en"` default is deliberate — `renew.py` still calls it with no `lang` argument until Task 6 lands; per Global Constraints, this is a temporary cross-task compatibility default.)

- [ ] **Step 4: Update `app/bot/handlers/buy.py`**

Full new content:

```python
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import (
    buy_category_keyboard,
    buy_plan_keyboard,
    buy_price_summary_keyboard,
    payment_link_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import CATEGORIES, category_display_name, format_data_cap, format_price_usd, get_plan, list_plans, plan_display_name
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.payments.nowpayments import NowPaymentsError, PaymentProviderNotConfiguredError
from app.services.payments.service import create_crypto_payment

logger = logging.getLogger(__name__)

router = Router(name="buy")

# Trial has its own dedicated flow (menu:trial) and must never be reachable
# through Buy — it's a real, $0.00 plan, not just an inactive one.
_BUY_CATEGORIES = tuple(category for category in CATEGORIES if category != "trial")


@router.callback_query(F.data == "menu:buy")
async def buy_start_cb(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        await callback.message.edit_text(t("buy_category_heading", lang), reply_markup=buy_category_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data.startswith("buy:category:"))
async def buy_category_cb(callback: CallbackQuery, lang: str) -> None:
    category = callback.data.split(":")[-1]
    if category not in _BUY_CATEGORIES:
        if callback.message is not None:
            await callback.message.edit_text(t("buy_category_heading", lang), reply_markup=buy_category_keyboard(lang))
        await callback.answer()
        return
    async with async_session_maker() as session:
        plans = await list_plans(session, category=category, active_only=True)
    if callback.message is not None:
        await callback.message.edit_text(t("buy_pick_plan", lang), reply_markup=buy_plan_keyboard(plans, lang))
    await callback.answer()


def _is_buyable(plan: Plan | None) -> bool:
    """Trial is a real, $0.00 plan — Buy must never expose it (that's menu:trial's job)."""
    return plan is not None and plan.category != "trial"


async def _price_summary_text(session: AsyncSession, plan: Plan, lang: str) -> str:
    lines = [
        f"🔑 <b>{plan_display_name(plan, lang)} ({category_display_name(plan.category, lang)})</b>",
        t("price_duration", lang, days=plan.duration_days),
        t("price_data", lang, cap=format_data_cap(plan.data_cap_mb)),
    ]
    discount = await find_best_auto_discount(session, plan.id)
    if discount is not None:
        discounted = discount_price(plan.price_usd, discount.percent)
        percent_text = f"{discount.percent.normalize():f}"
        lines.append(
            t("price_line_discounted", lang, original=format_price_usd(plan.price_usd), discounted=format_price_usd(discounted), percent=percent_text)
        )
    else:
        lines.append(t("price_line", lang, price=format_price_usd(plan.price_usd)))
    return "\n".join(lines)


@router.callback_query(F.data.startswith("buy:plan:"))
async def buy_plan_cb(callback: CallbackQuery, lang: str) -> None:
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            plan = None
        if plan is not None:
            text = await _price_summary_text(session, plan, lang)
    if plan is None:
        if callback.message is not None:
            await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()
        return
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=buy_price_summary_keyboard(plan.id, plan.category, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery, lang: str) -> None:
    plan_id = int(callback.data.split(":")[-1])
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="purchase", plan=plan, vpn_user=None,
            )
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        except NowPaymentsError:
            logger.error("NOWPayments invoice creation failed for plan %s", plan_id, exc_info=True)
            if callback.message is not None:
                await callback.message.edit_text(t("payment_unavailable", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

    if callback.message is not None:
        await callback.message.edit_text(t("payment_link_heading", lang), reply_markup=payment_link_keyboard(payment.invoice_url, lang))
    await callback.answer()
```

- [ ] **Step 5: Run this task's tests**

Run: `pytest tests/functional/test_buy_flow.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add app/bot/handlers/buy.py app/bot/keyboards/buy.py tests/functional/test_buy_flow.py
git commit -m "feat: migrate Buy Subscription flow to bilingual text"
```

---

## Task 6: renew.py + renew keyboard

**Files:**
- Modify: `app/bot/handlers/renew.py`, `app/bot/keyboards/renew.py`
- Test: `tests/functional/test_renew_flow.py` (append)

**Interfaces:**
- Consumes: `t`, `plan_display_name`, `category_display_name` (Task 1), `lang: str` injected (Task 2), `back_to_menu_keyboard(lang: str = "en")` (Task 3) and `payment_link_keyboard(invoice_url, lang: str = "en")` (Task 5) — this task starts passing `lang=lang` to both explicitly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/functional/test_renew_flow.py` (check its existing `_create_service`/`_plan_id` helpers first and reuse them):

```python
@pytest.mark.asyncio
async def test_renew_empty_state_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 840, None)
        await set_language(session, 840, "fa")

    await dispatcher.feed_update(bot, make_callback_update(840, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "تمدید سرویس" in edited[0][1]["text"]
    assert "ندارید" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_renew_summary_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.bot_users import record_seen, set_language

    telegram_id = 841
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="2 Weeks")
    new_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{new_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "تمدید" in edited[0][1]["text"]
    assert "قیمت:" in edited[0][1]["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_renew_flow.py -v -k persian`
Expected: FAIL.

- [ ] **Step 3: Update `app/bot/keyboards/renew.py`**

Full new content:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.i18n.texts import t
from app.services.catalog import category_display_name, format_data_cap, format_price_usd, plan_display_name


def renew_service_keyboard(rows: list[tuple[VPNUser, Plan | None]], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan in rows:
        name = plan.name if plan is not None else vpn_user.ibsng_group
        builder.button(text=name, callback_data=f"renew:service:{vpn_user.id}")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def renew_empty_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("menu_buy", lang), callback_data="menu:buy", style="success")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def renew_category_keyboard(vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=category_display_name("scroll", lang), callback_data=f"renew:category:{vpn_user_id}:scroll")
    builder.button(text=category_display_name("stream", lang), callback_data=f"renew:category:{vpn_user_id}:stream")
    builder.button(text=t("back_to_service_button", lang), callback_data="menu:renew")
    builder.adjust(2, 1)
    return builder.as_markup()


def renew_plan_keyboard(plans: list[Plan], vpn_user_id: int, category: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan_display_name(plan, lang)} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb)})",
            callback_data=f"renew:plan:{vpn_user_id}:{plan.id}",
        )
    builder.button(text=t("back_button", lang), callback_data=f"renew:service:{vpn_user_id}")
    builder.adjust(1)
    return builder.as_markup()


def renew_price_summary_keyboard(vpn_user_id: int, plan_id: int, category: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("pay_with_crypto_button", lang), callback_data=f"renew:confirm:{vpn_user_id}:{plan_id}", style="success")
    builder.button(text=t("back_button", lang), callback_data=f"renew:category:{vpn_user_id}:{category}")
    builder.adjust(1)
    return builder.as_markup()
```

(`renew_category_keyboard`'s "⬅️ Back to Services" button originally used a bespoke label distinct from myservices' `back_to_service_button` phrase; the spec's key table has no separate `renew_back_to_services` key, so this reuses `back_to_service_button` — both read naturally as "back to the [service/services] view" in context. If this distinction matters to you, flag it in review; it's a one-key addition to fix.)

- [ ] **Step 4: Update `app/bot/handlers/renew.py`**

Full new content:

```python
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import payment_link_keyboard
from app.bot.keyboards.renew import (
    renew_category_keyboard,
    renew_empty_keyboard,
    renew_plan_keyboard,
    renew_price_summary_keyboard,
    renew_service_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import CATEGORIES, category_display_name, format_data_cap, format_price_usd, get_plan, list_plans, plan_display_name
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.payments.nowpayments import NowPaymentsError, PaymentProviderNotConfiguredError
from app.services.payments.service import create_crypto_payment
from app.services.vpn_users import get_owned_vpn_user, list_renewable_services

logger = logging.getLogger(__name__)

router = Router(name="renew")

# Trial has no renewal concept - it's excluded from every category/tier
# screen in this flow, same as Buy excludes it from its own.
_RENEW_CATEGORIES = tuple(category for category in CATEGORIES if category != "trial")

_MAX_POSTGRES_INT = 2**31 - 1


def _parse_int(raw: str) -> int | None:
    """Parses a callback_data id segment as a plain integer, with no
    upper bound check. Used where an out-of-range-but-well-formed id
    should still flow into its lookup so it degrades through that
    lookup's own not-found/gone screen, rather than the generic
    not-found screen used for a segment that isn't a number at all."""
    try:
        return int(raw)
    except ValueError:
        return None


def _in_postgres_int_range(value: int) -> bool:
    """VPNUser.id and Plan.id are both PostgreSQL `integer` (int4)
    columns - a numerically valid but out-of-range value (e.g.
    "2147483648") passes int() only to raise an unhandled
    asyncpg.DataError once bound to a query."""
    return 0 < value <= _MAX_POSTGRES_INT


def _parse_id(raw: str) -> int | None:
    """Parses a callback_data id segment, rejecting anything that isn't
    a well-formed, in-range id - used where any invalid id (malformed or
    out-of-range) should degrade to the same generic not-found screen,
    because an invalid id here means we don't even know which record is
    being referenced."""
    value = _parse_int(raw)
    if value is None or not _in_postgres_int_range(value):
        return None
    return value


async def _not_found(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        await callback.message.edit_text(t("renew_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
    await callback.answer()


async def _service_display_name(session: AsyncSession, vpn_user: VPNUser) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    return plan.name if plan is not None else vpn_user.ibsng_group


@router.callback_query(F.data == "menu:renew")
async def renew_start_cb(callback: CallbackQuery, lang: str) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        rows = await list_renewable_services(session, telegram_id)

    if not rows:
        if callback.message is not None:
            await callback.message.edit_text(t("renew_empty", lang), reply_markup=renew_empty_keyboard(lang))
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(t("renew_list_heading", lang), reply_markup=renew_service_keyboard(rows, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:service:"))
async def renew_service_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback, lang)
            return
        name = await _service_display_name(session, vpn_user)

    text = t("renew_pick_category", lang, name=name)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=renew_category_keyboard(vpn_user_id, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:category:"))
async def renew_category_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback, lang)
            return
        name = await _service_display_name(session, vpn_user)

        category = parts[3] if len(parts) > 3 else ""
        if category not in _RENEW_CATEGORIES:
            text = t("renew_pick_category", lang, name=name)
            if callback.message is not None:
                await callback.message.edit_text(text, reply_markup=renew_category_keyboard(vpn_user_id, lang))
            await callback.answer()
            return

        plans = await list_plans(session, category=category, active_only=True)

    text = t("renew_pick_plan", lang, name=name)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=renew_plan_keyboard(plans, vpn_user_id, category, lang))
    await callback.answer()


def _is_renewable(plan: Plan | None) -> bool:
    """Trial is a real, $0.00 plan - Renew must never expose it, same
    reasoning as Buy's own _is_buyable."""
    return plan is not None and plan.category != "trial"


async def _renew_summary_text(session: AsyncSession, current_name: str, plan: Plan, lang: str) -> str:
    lines = [
        t("renew_summary_heading", lang, current=current_name, new=plan_display_name(plan, lang), category=category_display_name(plan.category, lang)),
        t("price_duration", lang, days=plan.duration_days),
        t("price_data", lang, cap=format_data_cap(plan.data_cap_mb)),
    ]
    discount = await find_best_auto_discount(session, plan.id)
    if discount is not None:
        discounted = discount_price(plan.price_usd, discount.percent)
        percent_text = f"{discount.percent.normalize():f}"
        lines.append(
            t("price_line_discounted", lang, original=format_price_usd(plan.price_usd), discounted=format_price_usd(discounted), percent=percent_text)
        )
    else:
        lines.append(t("price_line", lang, price=format_price_usd(plan.price_usd)))
    return "\n".join(lines)


@router.callback_query(F.data.startswith("renew:plan:"))
async def renew_plan_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return

    plan_id = _parse_int(parts[3]) if len(parts) > 3 else None
    if plan_id is None:
        await _not_found(callback, lang)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback, lang)
            return

        plan = await get_plan(session, plan_id) if _in_postgres_int_range(plan_id) else None
        if not _is_renewable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

        current_name = await _service_display_name(session, vpn_user)
        text = await _renew_summary_text(session, current_name, plan, lang)

    if callback.message is not None:
        await callback.message.edit_text(
            text, reply_markup=renew_price_summary_keyboard(vpn_user_id, plan.id, plan.category, lang)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("renew:confirm:"))
async def renew_confirm_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return

    plan_id = _parse_int(parts[3]) if len(parts) > 3 else None
    if plan_id is None:
        await _not_found(callback, lang)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback, lang)
            return

        plan = await get_plan(session, plan_id) if _in_postgres_int_range(plan_id) else None
        if not _is_renewable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="renew", plan=plan, vpn_user=vpn_user,
            )
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(t("payment_coming_soon_renew", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        except NowPaymentsError:
            logger.error(
                "NOWPayments invoice creation failed for vpn_user %s plan %s", vpn_user_id, plan_id, exc_info=True,
            )
            if callback.message is not None:
                await callback.message.edit_text(t("payment_unavailable", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

    # renew_and_change_group is deliberately never called here - no
    # renewal is executed until the webhook (app/webhook.py) reports the
    # payment as "finished".
    if callback.message is not None:
        await callback.message.edit_text(t("payment_link_heading", lang), reply_markup=payment_link_keyboard(payment.invoice_url, lang))
    await callback.answer()
```

- [ ] **Step 5: Run this task's tests**

Run: `pytest tests/functional/test_renew_flow.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add app/bot/handlers/renew.py app/bot/keyboards/renew.py tests/functional/test_renew_flow.py
git commit -m "feat: migrate Renew Service flow to bilingual text"
```

---

## Task 7: webhook.py buyer-visible messages

**Files:**
- Modify: `app/webhook.py`
- Test: `tests/functional/test_webhook.py` (append)

**Interfaces:**
- Consumes: `t` (Task 1), `get_language` (Task 1) — looked up directly via `payment.telegram_id`, NOT middleware-injected (this code runs in the aiohttp app, outside the dispatcher).

- [ ] **Step 1: Write the failing tests**

Check `tests/functional/test_webhook.py`'s existing test structure first (how it constructs a `Payment` row and posts the IPN payload) and reuse that exact setup. Append:

```python
@pytest.mark.asyncio
async def test_payment_confirmed_message_in_persian(aiohttp_client, ...) -> None:
    # Mirror this file's existing "finished" IPN test setup exactly, but:
    # 1. seed BotUser(telegram_id=<the payment's telegram_id>, language="fa")
    #    via app.services.bot_users.record_seen + set_language before
    #    posting the IPN
    # 2. after posting, assert "پرداخت تأیید شد" appears in the sent
    #    message text captured by fake_session
    ...
```

(This step is deliberately a template, not literal code — `test_webhook.py`'s existing fixture/helper names for constructing a signed IPN payload and a pending `Payment` row were not re-read in full this session; the implementer must open that file, copy its exact existing "finished" test's setup verbatim, and add only the two-line `BotUser` language seed plus the Persian-text assertion. Do not invent a different IPN-posting mechanism — match the file's own established pattern exactly.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_webhook.py -v -k persian`
Expected: FAIL.

- [ ] **Step 3: Update `app/webhook.py`**

Add the import:

```python
from app.i18n.texts import t
from app.services.bot_users import get_language
```

Inside `_handle_crypto_ipn`, wherever `payment.telegram_id` is about to be used to send a message, resolve `lang` first via the already-open `session`. The three message sites (transcribed with their surrounding context so the exact insertion point is unambiguous):

```python
            payment.status = "paid"
            payment.resolved_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            action_key = "action_renewed" if payment.purpose == "renew" else "action_activated"
            lang = (await get_language(session, payment.telegram_id)) or "en"
            await bot.send_message(
                payment.telegram_id,
                t("payment_confirmed", lang, username=username, action=t(action_key, lang)),
            )

        elif new_status == "partially_paid":
            payment.status = "partially_paid"
            payment.paid_amount = event.paid_amount
            await session.commit()
            # Deliberately no dollar shortfall figure here: actually_paid
            # (event.paid_amount) is in the invoice's pay_currency (e.g.
            # USDT units), not USD, and computing a USD shortfall
            # accurately needs the invoice's pay_currency/pay_amount
            # conversion ratio, which this design doesn't track. The
            # linked payment page itself shows the exact remaining
            # balance in the correct currency.
            lang = (await get_language(session, payment.telegram_id)) or "en"
            await bot.send_message(
                payment.telegram_id,
                t("partial_payment", lang),
                reply_markup=_topup_keyboard(payment, lang),
            )

        else:  # "failed" or "refunded"
            payment.status = new_status
            payment.resolved_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            if new_status == "failed":
                lang = (await get_language(session, payment.telegram_id)) or "en"
                await bot.send_message(payment.telegram_id, t("payment_failed", lang))
            # "refunded": recorded, no user-facing message defined for v1.

    return web.Response(status=200, text="ok")


async def _notify_activation_technical_issue(bot: Bot, payment: Payment) -> None:
    """Notify the user that their payment was received but activation hit
    a permanent technical issue. Tolerates the user having blocked the
    bot - that failure must never prevent the handler's 200 response,
    since NOWPayments would otherwise retry forever for a situation
    retrying can never fix."""
    try:
        async with async_session_maker() as session:
            lang = (await get_language(session, payment.telegram_id)) or "en"
        await bot.send_message(payment.telegram_id, t("activation_technical_issue", lang))
    except TelegramForbiddenError:
        logger.warning(
            "Payment %s: could not notify user %s - bot is blocked", payment.id, payment.telegram_id,
        )


def _topup_keyboard(payment: Payment, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if payment.invoice_url:
        builder.button(text=t("finish_payment_button", lang), url=payment.invoice_url)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
```

(`_notify_activation_technical_issue` didn't previously open its own session — it now does, briefly, just to resolve `lang`, since it's called from a spot in `_handle_crypto_ipn` where the enclosing `session` may already be closed by the time this function runs; check the exact call site and reuse the already-open `session` instead via a `lang` parameter if one is still in scope there — read the surrounding code before choosing between "open a new session" and "thread lang through as a parameter" and pick whichever matches this function's actual call site without changing its existing error-handling shape.)

- [ ] **Step 4: Run this task's tests**

Run: `pytest tests/functional/test_webhook.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add app/webhook.py tests/functional/test_webhook.py
git commit -m "feat: migrate NOWPayments webhook messages to bilingual text"
```

---

## Task 8: reminders.py

**Files:**
- Modify: `app/services/reminders.py`
- Test: `tests/functional/test_reminders.py` (append)

**Interfaces:**
- Consumes: `t`, `get_language` (Task 1) — direct lookup per candidate, same pattern as Task 7.

- [ ] **Step 1: Write the failing test**

Append to `tests/functional/test_reminders.py` (reuse its existing `_seed_vpn_user`/`_patch_status` helpers):

```python
@pytest.mark.asyncio
async def test_sends_persian_reminder_to_persian_user(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import datetime as dt

    from app.services.bot_users import record_seen, set_language
    from app.services.reminders import send_due_reminders

    telegram_id = 750
    await _seed_vpn_user(telegram_id)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await send_due_reminders(bot)

    sent = _sent(fake_session)
    assert len(sent) == 1
    assert "اعتبار سرویس شما" in sent[0][1]["text"]
    buttons = [b for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["text"] == "♻️ تمدید کنید" for b in buttons)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/functional/test_reminders.py -v -k persian`
Expected: FAIL.

- [ ] **Step 3: Update `app/services/reminders.py`**

Add the import:

```python
from app.i18n.texts import t
from app.services.bot_users import get_language
```

Replace `_MESSAGE_TEMPLATE` and `_renew_now_keyboard`'s use, and the send site inside `send_due_reminders`'s per-candidate loop:

```python
def _renew_now_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("renew_now_button", lang), callback_data="menu:renew")
    builder.adjust(1)
    return builder.as_markup()
```

Inside the `async with IBSngClient() as client:` loop, where the reminder is actually sent (replacing the existing `text = _MESSAGE_TEMPLATE.format(...)` / `reply_markup=_renew_now_keyboard()` lines):

```python
                lang = (await get_language(session, vpn_user.telegram_id)) or "en"
                text = t("reminder_message", lang, username=vpn_user.ibsng_username, days=window.days)
                try:
                    await bot.send_message(vpn_user.telegram_id, text, reply_markup=_renew_now_keyboard(lang))
                except Exception:
                    logger.exception("Failed to send expiry reminder to telegram_id=%s", vpn_user.telegram_id)
                    continue
```

(Remove the now-unused `_MESSAGE_TEMPLATE` module constant. `DEFAULT_DAYS_BEFORE` and every other constant/function in this file stay unchanged — this task touches only the message-formatting and keyboard-building lines.)

- [ ] **Step 4: Run this task's test**

Run: `pytest tests/functional/test_reminders.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add app/services/reminders.py tests/functional/test_reminders.py
git commit -m "feat: migrate renewal reminder messages to bilingual text"
```

---

## Task 9: error_handlers.py

**Files:**
- Modify: `app/bot/error_handlers.py`
- Test: `tests/functional/test_middlewares.py` (append, or wherever the project's existing pool-timeout test lives — search for it first: `grep -rl "handle_pool_timeout\|pool_busy\|PoolTimeoutError" tests/`)

**Interfaces:**
- Consumes: `t` (Task 1); `data["lang"]` if aiogram's error-handler DI actually injects it (verify in Step 3 below), else `get_language(session, chat_id)` directly.

- [ ] **Step 1: Locate the existing pool-timeout test**

Run: `grep -rl "handle_pool_timeout\|PoolTimeoutError" tests/`
Read whatever file it finds in full before writing anything — this task appends to that file, matching its exact existing setup for triggering a pool timeout (however it currently monkeypatches/raises `sqlalchemy.exc.TimeoutError` to exercise this handler).

- [ ] **Step 2: Write the failing test**

Append a Persian-path version of that file's existing pool-timeout test, seeding `BotUser(language="fa")` for the triggering telegram_id first via `record_seen`+`set_language`, and asserting the sent message contains `"سرور موقتاً شلوغ است"` instead of the English text.

- [ ] **Step 3: Run test to verify it fails, and determine the injection mechanism**

Run: `pytest tests/ -v -k pool_timeout_persian` (or whatever the new test is named)
Expected: FAIL. While implementing Step 4, empirically determine whether aiogram's `ErrorsMiddleware` actually re-injects the triggering update's `data` dict (containing `lang`, set by `LanguageMiddleware` during that same update's earlier processing) into `handle_pool_timeout`'s kwargs when the function declares a `data: dict` parameter. Try it first; if aiogram raises a `TypeError`/`SkipHandler`-style error resolving that parameter, or if `data.get("lang")` is empty/missing at runtime, fall back to the direct-query approach below instead — do not leave a half-working injection in place.

- [ ] **Step 4: Update `app/bot/error_handlers.py`**

Preferred version (if Step 3 confirms `data` injection works):

```python
"""Global aiogram error handler - registered once in main.py via
dp.errors.register(...). Handles a DB connection-pool timeout with a
clear message instead of the unhandled-exception path every other
error still takes.

Anything that is NOT a pool timeout must return the UNHANDLED sentinel,
not a falsy value: aiogram's ErrorsMiddleware only re-raises the original
exception when the error handler's response `is UNHANDLED`. Returning
False here would mark every bug in every handler as "handled" and
discard it silently, with no traceback anywhere."""

from __future__ import annotations

import logging
from typing import Any

from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.i18n.texts import t

logger = logging.getLogger(__name__)


async def handle_pool_timeout(event: ErrorEvent, data: dict[str, Any]) -> Any:
    if not isinstance(event.exception, PoolTimeoutError):
        return UNHANDLED

    inner: Message | CallbackQuery | None = event.update.message or event.update.callback_query
    chat_id = None
    if isinstance(inner, Message):
        chat_id = inner.chat.id
    elif isinstance(inner, CallbackQuery) and inner.message is not None:
        chat_id = inner.message.chat.id

    logger.warning("DB connection pool exhausted (update_id=%s, chat_id=%s)", event.update.update_id, chat_id)

    if chat_id is not None:
        lang = data.get("lang", "en")
        try:
            await event.update.bot.send_message(chat_id, t("pool_busy", lang))
        except Exception:
            logger.exception("Could not deliver the pool-busy message to chat_id=%s", chat_id)
    return True
```

Fallback version (if Step 3 finds the injection doesn't work):

```python
"""Global aiogram error handler - registered once in main.py via
dp.errors.register(...). Handles a DB connection-pool timeout with a
clear message instead of the unhandled-exception path every other
error still takes.

Anything that is NOT a pool timeout must return the UNHANDLED sentinel,
not a falsy value: aiogram's ErrorsMiddleware only re-raises the original
exception when the error handler's response `is UNHANDLED`. Returning
False here would mark every bug in every handler as "handled" and
discard it silently, with no traceback anywhere."""

from __future__ import annotations

import logging
from typing import Any

from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.bot_users import get_language

logger = logging.getLogger(__name__)


async def handle_pool_timeout(event: ErrorEvent) -> Any:
    if not isinstance(event.exception, PoolTimeoutError):
        return UNHANDLED

    inner: Message | CallbackQuery | None = event.update.message or event.update.callback_query
    chat_id = None
    if isinstance(inner, Message):
        chat_id = inner.chat.id
    elif isinstance(inner, CallbackQuery) and inner.message is not None:
        chat_id = inner.message.chat.id

    logger.warning("DB connection pool exhausted (update_id=%s, chat_id=%s)", event.update.update_id, chat_id)

    if chat_id is not None:
        # chat_id == telegram_id is safe here: PrivateChatOnlyMiddleware
        # already guarantees every update reaching this handler is a 1:1 DM.
        try:
            async with async_session_maker() as session:
                lang = (await get_language(session, chat_id)) or "en"
        except Exception:
            lang = "en"
        try:
            await event.update.bot.send_message(chat_id, t("pool_busy", lang))
        except Exception:
            logger.exception("Could not deliver the pool-busy message to chat_id=%s", chat_id)
    return True
```

Use whichever version Step 3 actually confirmed working — do not guess; the test from Step 2 is the proof either way.

- [ ] **Step 5: Run this task's test**

Run: the same targeted run from Step 3.
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add app/bot/error_handlers.py tests/  # exact test file path found in Step 1
git commit -m "feat: migrate pool-timeout error message to bilingual text"
```

---

## Task 10: Leak verification + CLAUDE.md + skill-doc updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/skills/aiogram-menu-flow-conventions/SKILL.md`
- Test: `tests/functional/test_i18n_leak.py` (new)

**Interfaces:**
- Consumes: nothing new — this task is verification-only plus documentation.

- [ ] **Step 1: Write the failing test**

Create `tests/functional/test_i18n_leak.py`:

```python
from __future__ import annotations

from pathlib import Path

_ADMIN_MODULES = (
    "admin.py",
    "admin_admins.py",
    "admin_block.py",
    "admin_discounts.py",
    "admin_renew.py",
    "admin_settings.py",
    "admin_fallback.py",
    "broadcast.py",
    "tutorial_admin.py",
)


def test_no_admin_facing_handler_imports_i18n() -> None:
    handlers_dir = Path(__file__).resolve().parents[2] / "app" / "bot" / "handlers"
    offenders = []
    for name in _ADMIN_MODULES:
        path = handlers_dir / name
        assert path.exists(), f"expected admin handler module not found: {path}"
        content = path.read_text()
        if "app.i18n" in content or "from app.i18n" in content:
            offenders.append(name)
    assert offenders == [], f"admin-facing modules must never import app.i18n: {offenders}"
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `pytest tests/functional/test_i18n_leak.py -v`
Expected: PASS immediately — this test's whole purpose is to have been true throughout Tasks 1-9 already (every prior task's Global Constraints explicitly excluded admin modules), so this step is confirmation, not a fix. If it fails, that is a real regression from an earlier task and must be fixed before continuing — do not silently adjust this test's module list to make a real leak pass.

- [ ] **Step 3: Update `CLAUDE.md`**

In the Conventions section, replace:

```
- All user-facing AND admin-facing strings in English.
```

with:

```
- Customer-facing strings are bilingual (fa/en) via app/i18n/texts.py's
  t(key, lang) - see docs/superpowers/specs/2026-09-18-bilingual-customer-
  flows-design.md. Admin-facing strings (everything under
  app/bot/handlers/admin*.py, admin_settings, admin_block, broadcast,
  tutorial_admin, and the adm:* screen tree) stay English-only - never
  route an admin-only string through t().
```

- [ ] **Step 4: Update the skill doc**

In `.claude/skills/aiogram-menu-flow-conventions/SKILL.md`, replace the entire "## English-only copy" section:

```
## English-only copy

Every user-facing AND admin-facing string is English, full stop - no
Persian/Farsi text anywhere in this bot (Homeland sells to Iranian
customers living *abroad*, unlike its sibling project AloBot which is
Persian-language for customers inside Iran - don't port AloBot's Farsi
strings by habit).
```

with:

```
## Bilingual customer-facing copy, English-only admin copy

Customer-facing strings are bilingual (fa/en), selected once by the
customer and reused thereafter - see
docs/superpowers/specs/2026-09-18-bilingual-customer-flows-design.md.
Every string shown to a customer goes through app/i18n/texts.py's
t(key, lang, **kwargs), never a hardcoded literal.

Admin-facing strings stay English-only, full stop - everything under
app/bot/handlers/admin*.py, admin_settings, admin_block, broadcast,
tutorial_admin, and the adm:* screen tree. Never route an admin-only
string through t(), and never import app.i18n into an admin-facing
handler module.
```

- [ ] **Step 5: Run the full suite one final time**

Run: `pytest tests/ -v`
Expected: PASS, every test in the project green.

- [ ] **Step 6: Commit**

```bash
git add tests/functional/test_i18n_leak.py CLAUDE.md .claude/skills/aiogram-menu-flow-conventions/SKILL.md
git commit -m "test: verify admin modules stay untouched by i18n; update conventions docs"
```

---

## Self-Review

**1. Spec coverage:**
- §1 (Summary, scope) → Global Constraints + every task's file list.
- §2 (Scope/boundaries 1-5) → boundaries 1-3 followed exactly in Tasks 3/5/6 (admin-authored content, protocol/platform labels, and `format_price_usd`/`format_data_cap` all left untouched); boundary 4 (Scroll/Stream transliteration) implemented via `category_display_name` in Task 1, consumed in Tasks 5-6; boundary 5 verified by Task 10's leak test.
- §3 (data model) → Task 1, transcribed verbatim.
- §4 (middleware + chooser flow, corrected during spec self-review to thread `lang` via aiogram's data-dict injection rather than manual parameter passing) → Task 2, transcribed verbatim including the corrected `send_main_menu`/`main_menu`/`menu_root_cb`/`fallback_to_main_menu` shapes.
- §5 (i18n module) → Task 1, `TEXTS`/`t()`/`CHOOSE_LANGUAGE_TEXT` transcribed verbatim, including the corrected 83-key parity claim.
- §6 (plan display names) → Task 1.
- §7 (all 83 keys) → Task 1's `texts.py`, and every key is actually consumed somewhere across Tasks 2-9 (cross-checked below in Type Consistency).
- §8 (out-of-band lookups: webhook, reminders, error_handlers, deliver_setup/`_send_trial_credentials` lang-threading) → Tasks 7, 8, 9, and 3 respectively.
- §9 (CLAUDE.md + skill-doc updates) → Task 10.
- §10 (testing strategy: per-module fa-path tests, `t()` unit tests, key-parity test, reminder test, leak-verification test) → present in every task exactly where the spec calls for it.
- §11 (spec's own self-review flags: Scroll/Stream transliteration, Persian numerals in prose, two separate `payment_coming_soon`/`payment_coming_soon_renew` keys) → all three decisions carried through unchanged into Tasks 1/5/6 — flagged again here as still open for your review, not silently resolved by this plan.

**2. Placeholder scan:** Every task has complete, runnable code for every file it touches, transcribed either directly from the spec (Tasks 1-2) or freshly written against this session's own full reading of each file's pre-migration content (Tasks 3-9) — no "similar to Task N" shortcuts. The one deliberate exception is Task 7's Step 1, which is explicitly labeled a template rather than literal code, because `test_webhook.py`'s exact existing IPN-posting helper signature was not re-read in full this session; the step names precisely what the implementer must do (read the file, copy its exact pattern) rather than guessing at a helper signature that might not match.

**3. Type consistency:**
- Every handler function across Tasks 2-9 that renders a translated string declares `lang: str` as a plain parameter name, consistent with aiogram's data-dict-key-name injection convention established in Task 2 — verified no task uses a different parameter name (e.g. `language:` or `user_lang:`) that would silently fail to receive the injected value.
- `back_to_menu_keyboard(lang: str = "en")` (defined Task 3) is called with an explicit `lang=lang`... actually positional `lang` in Tasks 3/5's own module, and consumed with the same explicit positional/keyword `lang` argument in Tasks 4 and 6 once those modules migrate — confirmed no task calls it with a keyword name other than positional `lang`.
- `payment_link_keyboard(invoice_url: str, lang: str = "en")` (defined Task 5) is called as `payment_link_keyboard(payment.invoice_url, lang)` in both Task 5 (buy.py) and Task 6 (renew.py) — same positional order in both call sites.
- `deliver_setup(..., lang: str = "en")` (Task 3) is called with `lang=lang` as a keyword argument in both Task 3 (trial.py, 2 call sites) and Task 4 (myservices.py, 2 call sites) — consistent keyword usage.
- `plan_display_name(plan, lang)`/`category_display_name(category, lang)` (Task 1) signatures match every call site in Tasks 5 and 6 exactly (positional `plan`/`category` then `lang`).
- Spot-checked every `t("<key>", lang, ...)` call introduced in Tasks 2-9 against Task 1's `TEXTS["en"]` key list (reproduced in full in Task 1, Step 8): `welcome`, `menu_buy` through `menu_language`, `placeholder_coming_soon`, `support_heading`, `support_not_configured`, `contact_support_button`, `back_to_menu`, `language_updated` (Task 2); `buy_category_heading` through `price_line_discounted` (Task 5); `renew_list_heading` through `payment_coming_soon_renew` (Task 6); `myservices_heading` through `back_to_service_button` (Task 4); `trial_already_used` through `confirm_button` (Task 3); `android_l2tp_unsupported` through `any_platform_label` (Task 3, tutorial_delivery.py); `payment_confirmed` through `finish_payment_button` (Task 7); `pool_busy` (Task 9); `reminder_message`/`renew_now_button` (Task 8); `plan_name_*` (Task 1/consumed via `plan_display_name`, Tasks 5-6). Every key referenced across Tasks 2-9 exists in Task 1's dict — no orphaned `t()` call to a key that was never defined.
