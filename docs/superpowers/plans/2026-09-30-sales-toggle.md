# Sales Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A full-admin switch under Financial that pauses every new purchase, renewal and trial activation, showing customers an admin-editable bilingual message instead.

**Architecture:** One `app_config`-backed service (`app/services/sales_status.py`) holds the flag and the messages. One gate function (`app/bot/sales_gate.py`) is called at the top of exactly six customer handlers. One new English-only admin router (`app/bot/handlers/admin_sales.py`) sets the flag and edits the messages, and logs each real state change to a new `🛠 Admin Actions` log topic.

**Tech Stack:** Python 3.12, aiogram 3, SQLAlchemy 2 async, pytest-asyncio, Docker test stack.

**Spec:** `docs/superpowers/specs/2026-09-30-sales-toggle-design.md`

## Global Constraints

- Flag key `sales_enabled`; absent or anything but `"false"` means enabled. No migration.
- Message keys `sales_paused_message_fa`, `sales_paused_message_en`; empty means "use default".
- Custom message: plain text, HTML-escaped on render, max 3500 characters.
- Customer strings via `t()` only; admin strings English and never import `app.i18n` in admin handler modules.
- Gate exactly these six handlers: `buy_plan_cb`, `buy_confirm_cb`, `renew_plan_cb`, `renew_confirm_cb`, `trial_entry_cb`, `trial_confirm_cb`. Never gate `app/services/payments/confirmation.py`, the reconciler, the webhook, My Services, or admin renew.
- Never rename an existing `adm:*` callback. New callbacks: `adm:fin:sales`, `adm:fin:sales:set:off`, `adm:fin:sales:set:on`, `adm:fin:sales:msg:fa`, `adm:fin:sales:msg:en`, `adm:fin:sales:reset`.
- Async only; type hints on every signature; thin handlers.

## Running tests

The test image bakes the source in (no volume), so rebuild before each targeted run:

```bash
T="docker compose -f docker-compose.test.yml -p homeland_bot_test"
$T up -d --build && $T exec -T test-runner pip install -q -r requirements-dev.txt
$T exec -T test-runner python -m pytest tests/functional/<file>.py -v
```

`make test` runs the full suite the same way.

---

### Task 1: Sales status service + customer texts

**Files:**
- Create: `app/services/sales_status.py`
- Modify: `app/i18n/texts.py` (add two keys to both `en` and `fa`)
- Test: `tests/functional/test_sales_status.py`

**Interfaces:**
- Produces:
  - `MESSAGE_LANGUAGES: tuple[str, ...] = ("fa", "en")`
  - `MAX_PAUSED_MESSAGE_LENGTH: int = 3500`
  - `async are_sales_enabled(session: AsyncSession) -> bool`
  - `async set_sales_enabled(session: AsyncSession, enabled: bool) -> None`
  - `async get_custom_paused_message(session: AsyncSession, lang: str) -> str | None`
  - `async set_custom_paused_message(session: AsyncSession, lang: str, text: str) -> None` (raises `ValueError` for a lang not in `MESSAGE_LANGUAGES`)
  - `async clear_custom_paused_messages(session: AsyncSession) -> None`
  - `default_paused_message(lang: str) -> str`
  - `async sales_paused_text(session: AsyncSession, lang: str) -> str`
  - i18n keys `sales_paused_default`, `back_to_main_menu`

- [ ] **Step 1: Write the failing tests**

`tests/functional/test_sales_status.py`:

```python
"""The sales switch and the paused message, below the handlers."""

from __future__ import annotations

import pytest

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_sales_are_enabled_by_default() -> None:
    from app.services.sales_status import are_sales_enabled

    async with async_session_maker() as session:
        assert await are_sales_enabled(session) is True


@pytest.mark.asyncio
async def test_disabling_persists_across_fresh_sessions() -> None:
    """A bot restart reads the flag from the DB, which is exactly what a
    fresh session does."""
    from app.services.app_config import get_config
    from app.services.sales_status import are_sales_enabled, set_sales_enabled

    async with async_session_maker() as session:
        await set_sales_enabled(session, False)
    async with async_session_maker() as session:
        assert await are_sales_enabled(session) is False
        assert await get_config(session, "sales_enabled") == "false"

    async with async_session_maker() as session:
        await set_sales_enabled(session, True)
    async with async_session_maker() as session:
        assert await are_sales_enabled(session) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lang", "fragment"),
    [("en", "Sales are temporarily paused"), ("fa", "فروش موقتاً متوقف شده است")],
)
async def test_default_message_when_nothing_is_set(lang: str, fragment: str) -> None:
    from app.services.sales_status import get_custom_paused_message, sales_paused_text

    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, lang) is None
        assert fragment in await sales_paused_text(session, lang)


@pytest.mark.asyncio
async def test_custom_message_is_per_language() -> None:
    from app.services.sales_status import sales_paused_text, set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "fa", "فروش بسته است")
    async with async_session_maker() as session:
        assert await sales_paused_text(session, "fa") == "فروش بسته است"
        # English was not set, so it still falls back to its default.
        assert "Sales are temporarily paused" in await sales_paused_text(session, "en")


@pytest.mark.asyncio
async def test_custom_message_is_html_escaped() -> None:
    from app.services.sales_status import sales_paused_text, set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "en", "Back <soon> & better")
        assert await sales_paused_text(session, "en") == "Back &lt;soon&gt; &amp; better"


@pytest.mark.asyncio
async def test_unknown_language_reads_the_english_message() -> None:
    from app.services.sales_status import sales_paused_text, set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "en", "Closed")
        assert await sales_paused_text(session, "de") == "Closed"


@pytest.mark.asyncio
async def test_clearing_restores_both_defaults() -> None:
    from app.services.sales_status import (
        clear_custom_paused_messages,
        get_custom_paused_message,
        set_custom_paused_message,
    )

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "fa", "الف")
        await set_custom_paused_message(session, "en", "A")
        await clear_custom_paused_messages(session)
    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "fa") is None
        assert await get_custom_paused_message(session, "en") is None


@pytest.mark.asyncio
async def test_setting_an_unsupported_language_is_refused() -> None:
    from app.services.sales_status import set_custom_paused_message

    async with async_session_maker() as session:
        with pytest.raises(ValueError):
            await set_custom_paused_message(session, "de", "Geschlossen")
```

- [ ] **Step 2: Run to verify failure**

Run: `$T exec -T test-runner python -m pytest tests/functional/test_sales_status.py -v` (after the rebuild line)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.sales_status'`

- [ ] **Step 3: Add the i18n keys**

In `app/i18n/texts.py`, in the `"en"` dict next to `"back_to_menu_short"`:

```python
        "back_to_main_menu": "🔙 Back to Main Menu",
        "sales_paused_default": (
            "⏸ <b>Sales are temporarily paused.</b>\n\n"
            "New purchases, renewals and trial activations are unavailable right now. "
            "Your active services keep working as usual. Please try again later."
        ),
```

In the `"fa"` dict next to its `"back_to_menu_short"`:

```python
        "back_to_main_menu": "🔙 بازگشت به منوی اصلی",
        "sales_paused_default": (
            "⏸ <b>فروش موقتاً متوقف شده است.</b>\n\n"
            "در حال حاضر امکان خرید، تمدید یا فعال‌سازی سرویس تست وجود ندارد. "
            "سرویس‌های فعال شما بدون تغییر کار می‌کنند. لطفاً کمی بعد دوباره تلاش کنید."
        ),
```

- [ ] **Step 4: Write the service**

`app/services/sales_status.py`:

```python
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
#: Leaves headroom under Telegram's 4096-character message limit.
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
```

- [ ] **Step 5: Run to verify pass**

Run: rebuild, then `$T exec -T test-runner python -m pytest tests/functional/test_sales_status.py tests/functional/test_i18n.py -v`
Expected: all PASS (test_i18n confirms the new keys match between languages).

- [ ] **Step 6: Commit**

```bash
git add app/services/sales_status.py app/i18n/texts.py tests/functional/test_sales_status.py
git commit -m "feat: sales status service and paused-message texts"
```

---

### Task 2: The gate, wired into the six handlers

**Files:**
- Create: `app/bot/keyboards/sales_gate.py`
- Create: `app/bot/sales_gate.py`
- Modify: `app/bot/handlers/buy.py` (`buy_plan_cb`, `buy_confirm_cb`)
- Modify: `app/bot/handlers/renew.py` (`renew_plan_cb`, `renew_confirm_cb`)
- Modify: `app/bot/handlers/trial.py` (`trial_entry_cb`, `trial_confirm_cb`)
- Test: `tests/functional/test_sales_gate.py`

**Interfaces:**
- Consumes: `are_sales_enabled`, `sales_paused_text`, `set_sales_enabled`, `set_custom_paused_message` (Task 1); `show_screen` from `app/bot/keyboards/menus.py`.
- Produces: `async block_if_sales_paused(callback: CallbackQuery, lang: str) -> bool`; `sales_paused_keyboard(lang: str) -> InlineKeyboardMarkup`.

- [ ] **Step 1: Write the failing tests**

`tests/functional/test_sales_gate.py`:

```python
"""While sales are disabled, each of the six gated handlers answers with
the paused message and touches neither Plisio nor IBSng. Everything else -
the menus, My Services, a paid invoice - keeps working."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.session import async_session_maker
from tests.factories import make_callback_update, make_photo_message
from tests.fakes.fake_bot_session import FakeBotSession

_PAUSED_EN = "Sales are temporarily paused"


async def _pause() -> None:
    from app.services.sales_status import set_sales_enabled

    async with async_session_maker() as session:
        await set_sales_enabled(session, False)


async def _use_persian(telegram_id: int) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")


def _plan_id(seeded_catalog: dict) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll" and p["name"] == "1 Month")


async def _create_service(seeded_catalog: dict, telegram_id: int) -> Any:
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    plan = next(p for p in seeded_catalog["plans"] if p["id"] == _plan_id(seeded_catalog))
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        return await create_vpn_user(
            session, client, telegram_id=telegram_id, username=username, password=password,
            group_name=plan["group_name"], data_cap_mb=plan["data_cap_mb"], plan_id=plan["id"], is_trial=False,
        )


def _forbid_invoices(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    async def _no_invoice(self: CryptoProvider, **_: Any) -> tuple[str, str]:
        raise AssertionError("an invoice was created while sales were disabled")

    monkeypatch.setattr(CryptoProvider, "create_invoice", _no_invoice)


async def _payment_count() -> int:
    from app.db.models.payment import Payment

    async with async_session_maker() as session:
        return (await session.execute(select(func.count()).select_from(Payment))).scalar_one()


async def _vpn_user_count(telegram_id: int) -> int:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        return (
            await session.execute(select(func.count()).select_from(VPNUser).where(VPNUser.telegram_id == telegram_id))
        ).scalar_one()


def _last_screen(fake_session: FakeBotSession) -> dict[str, Any]:
    screens = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    return screens[-1][1]


def _assert_paused(screen: dict[str, Any], *, text_fragment: str = _PAUSED_EN, back: str = "🔙 Back to Main Menu") -> None:
    assert text_fragment in screen["text"]
    buttons = [b for row in screen["reply_markup"]["inline_keyboard"] for b in row]
    assert [(b["text"], b["callback_data"]) for b in buttons] == [(back, "menu:root")]


# --- the six gated handlers --------------------------------------------------


@pytest.mark.asyncio
async def test_buy_plan_is_blocked(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5101, f"buy:plan:{_plan_id(seeded_catalog)}"))
    _assert_paused(_last_screen(fake_session))


@pytest.mark.asyncio
async def test_buy_confirm_is_blocked_and_creates_no_invoice(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_invoices(monkeypatch)
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5102, f"buy:confirm:{_plan_id(seeded_catalog)}"))
    _assert_paused(_last_screen(fake_session))
    assert await _payment_count() == 0


@pytest.mark.asyncio
async def test_renew_plan_is_blocked(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    service = await _create_service(seeded_catalog, 5103)
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5103, f"renew:plan:{service.id}:{_plan_id(seeded_catalog)}"))
    _assert_paused(_last_screen(fake_session))


@pytest.mark.asyncio
async def test_renew_confirm_is_blocked_and_creates_no_invoice(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_invoices(monkeypatch)
    service = await _create_service(seeded_catalog, 5104)
    await _pause()
    await dispatcher.feed_update(
        bot, make_callback_update(5104, f"renew:confirm:{service.id}:{_plan_id(seeded_catalog)}")
    )
    _assert_paused(_last_screen(fake_session))
    assert await _payment_count() == 0


@pytest.mark.asyncio
async def test_trial_entry_is_blocked(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5105, "menu:trial"))
    _assert_paused(_last_screen(fake_session))


@pytest.mark.asyncio
async def test_trial_confirm_is_blocked_and_creates_no_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """An old trial:confirm button from before the pause must not slip through."""
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5106, "trial:confirm"))
    _assert_paused(_last_screen(fake_session))
    assert await _vpn_user_count(5106) == 0


@pytest.mark.asyncio
async def test_trial_from_a_campaign_photo_sends_a_fresh_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A campaign photo's button reuses menu:trial; a photo can't be
    edited into text, so the gate must send a new message instead."""
    await _pause()
    photo = make_photo_message(5107, file_id="campaign-photo")
    await dispatcher.feed_update(bot, make_callback_update(5107, "menu:trial", anchor_message=photo))
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert sent, "expected a fresh message, not an edit"
    _assert_paused(sent[-1][1])


# --- language and custom text ------------------------------------------------


@pytest.mark.asyncio
async def test_persian_user_sees_the_persian_default(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await _use_persian(5108)
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5108, f"buy:plan:{_plan_id(seeded_catalog)}"))
    _assert_paused(
        _last_screen(fake_session), text_fragment="فروش موقتاً متوقف شده است", back="🔙 بازگشت به منوی اصلی"
    )


@pytest.mark.asyncio
async def test_custom_message_is_shown_in_the_users_language(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.sales_status import set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "fa", "فروش تا فردا بسته است <تعمیرات>")
        await set_custom_paused_message(session, "en", "Closed until tomorrow <maintenance>")
    await _pause()
    await _use_persian(5109)

    await dispatcher.feed_update(bot, make_callback_update(5109, "menu:trial"))
    assert _last_screen(fake_session)["text"] == "فروش تا فردا بسته است &lt;تعمیرات&gt;"

    await dispatcher.feed_update(bot, make_callback_update(5110, "menu:trial"))
    assert _last_screen(fake_session)["text"] == "Closed until tomorrow &lt;maintenance&gt;"


# --- enabled: nothing changes ------------------------------------------------


@pytest.mark.asyncio
async def test_buy_plan_shows_the_price_summary_when_sales_are_enabled(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(5111, f"buy:plan:{_plan_id(seeded_catalog)}"))
    screen = _last_screen(fake_session)
    assert _PAUSED_EN not in screen["text"]
    assert "1 Month" in screen["text"]


@pytest.mark.asyncio
async def test_trial_entry_shows_the_confirm_prompt_when_sales_are_enabled(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(5112, "menu:trial"))
    screen = _last_screen(fake_session)
    assert _PAUSED_EN not in screen["text"]
    assert any(b["callback_data"] == "trial:confirm" for row in screen["reply_markup"]["inline_keyboard"] for b in row)


# --- disabled: the rest of the bot is untouched --------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["menu:buy", "buy:category:scroll", "menu:renew"])
async def test_menus_stay_visible_while_paused(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5113, data))
    assert _PAUSED_EN not in _last_screen(fake_session)["text"]


@pytest.mark.asyncio
async def test_my_services_and_account_management_work_while_paused(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _create_service(seeded_catalog, 5114)
    await _pause()

    for data in (
        "menu:myservices",
        "myservices:list",
        f"myservices:view:{service.id}",
        f"myservices:detail:{service.id}",
        f"myservices:pw:{service.id}",
    ):
        await dispatcher.feed_update(bot, make_callback_update(5114, data))
        assert _PAUSED_EN not in _last_screen(fake_session)["text"], data

    await dispatcher.feed_update(bot, make_callback_update(5114, f"myservices:pwdo:{service.id}"))
    assert "Password: <code>" in _last_screen(fake_session)["text"], "the reset still runs"


@pytest.mark.asyncio
async def test_an_invoice_paid_while_paused_is_still_provisioned(
    bot: Any, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The customer already paid; the switch only stops NEW sales."""
    from app.db.models.payment import Payment
    from app.services.catalog import get_plan
    from app.services.payments.confirmation import ACTIVATED, confirm_paid_payment
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return f"https://plisio.net/invoice/{order_id}", f"plisio-paused-{order_id}"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    async with async_session_maker() as session:
        plan = await get_plan(session, _plan_id(seeded_catalog))
        payment = await create_crypto_payment(session, telegram_id=5115, purpose="purchase", plan=plan, vpn_user=None)

    await _pause()

    async with async_session_maker() as session:
        row = await session.get(Payment, payment.id)
        result = await confirm_paid_payment(bot, session, row)
    assert result.outcome == ACTIVATED
```

- [ ] **Step 2: Run to verify failure**

Run: rebuild, then `$T exec -T test-runner python -m pytest tests/functional/test_sales_gate.py -v`
Expected: the six blocked-handler tests and both language tests FAIL (the flows proceed as normal); the enabled/unaffected tests PASS already.

If `myservices:pwdo` shows a password line with different wording, read `app/bot/handlers/myservices.py`'s `pwdo` handler and assert on its real success text instead. The point is that the reset ran.

- [ ] **Step 3: Write the keyboard**

`app/bot/keyboards/sales_gate.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t


def sales_paused_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("back_to_main_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Write the gate**

`app/bot/sales_gate.py`:

```python
"""The ONE customer-side check of the sales switch.

Called first thing in exactly six handlers - buy:plan, buy:confirm,
renew:plan, renew:confirm, menu:trial, trial:confirm - so a customer can
browse the menus but is stopped the moment they pick something. The
confirm handlers re-check because an old button in chat history can
reach them without passing the first step. Never gate payment
confirmation: an invoice that is already paid is always honored."""

from __future__ import annotations

from aiogram.types import CallbackQuery

from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.sales_gate import sales_paused_keyboard
from app.db.session import async_session_maker
from app.services.sales_status import are_sales_enabled, sales_paused_text


async def block_if_sales_paused(callback: CallbackQuery, lang: str) -> bool:
    """True when sales are paused - the paused screen is already shown
    and the callback answered, so the caller just returns."""
    async with async_session_maker() as session:
        if await are_sales_enabled(session):
            return False
        text = await sales_paused_text(session, lang)
    if callback.message is not None:
        # show_screen, not edit_text: menu:trial can arrive from an Ad
        # Campaign photo, which cannot be edited into a text screen.
        await show_screen(callback.message, text, sales_paused_keyboard(lang))
    await callback.answer()
    return True
```

- [ ] **Step 5: Wire the six handlers**

In each of `buy.py`, `renew.py`, `trial.py` add the import:

```python
from app.bot.sales_gate import block_if_sales_paused
```

Then make these two lines the FIRST statements in each of the six handler bodies (after the docstring, where there is one, and before any parsing or DB work):

```python
    if await block_if_sales_paused(callback, lang):
        return
```

- `app/bot/handlers/buy.py`: `buy_plan_cb` (before `plan_id = int(...)`), `buy_confirm_cb` (before `plan_id = int(...)`)
- `app/bot/handlers/renew.py`: `renew_plan_cb` (before `parts = ...`), `renew_confirm_cb` (before `parts = ...`)
- `app/bot/handlers/trial.py`: `trial_entry_cb` (before the `has_used_trial` block), `trial_confirm_cb` (before `telegram_id = ...`)

Do not touch any other handler.

- [ ] **Step 6: Run to verify pass**

Run: rebuild, then `$T exec -T test-runner python -m pytest tests/functional/test_sales_gate.py tests/functional/test_buy_flow.py tests/functional/test_renew_flow.py tests/functional/test_trial_flow.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/bot/sales_gate.py app/bot/keyboards/sales_gate.py app/bot/handlers/buy.py app/bot/handlers/renew.py app/bot/handlers/trial.py tests/functional/test_sales_gate.py
git commit -m "feat: gate purchase, renewal and trial on the sales switch"
```

---

### Task 3: Admin screen, log event, and docs

**Files:**
- Modify: `app/services/adminlog.py` (new event + topic)
- Create: `app/bot/keyboards/admin_sales.py`
- Create: `app/bot/states/admin_sales.py`
- Create: `app/bot/handlers/admin_sales.py`
- Modify: `app/bot/keyboards/admin.py` (`admin_financial_menu`)
- Modify: `app/main.py` (import + `include_router`)
- Modify: `tests/functional/test_i18n_leak.py` (add `admin_sales.py` to `_ADMIN_MODULES`)
- Modify: `CLAUDE.md` (one Architecture bullet)
- Test: `tests/functional/test_admin_sales.py`

**Interfaces:**
- Consumes: everything from Task 1; `log_event(bot, key, **values)` from `app/services/adminlog.py`; `IsFullAdmin` from `app/bot/filters/admin.py`.
- Produces: `adminlog.SALES_STATUS = "sales_status"`, `adminlog.TOPIC_ADMIN_ACTIONS = "admin_actions"`; `sales_status_keyboard(*, enabled: bool)`, `sales_message_cancel_keyboard()`; `EditSalesMessageStates.text`.

- [ ] **Step 1: Write the failing tests**

`tests/functional/test_admin_sales.py`:

```python
"""Financial → Sales Status: full admins only, English only."""

from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


def _last_screen(fake_session: FakeBotSession) -> dict[str, Any]:
    screens = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    return screens[-1][1]


def _buttons(screen: dict[str, Any]) -> dict[str, str]:
    markup = screen.get("reply_markup") or {"inline_keyboard": []}
    return {b["text"]: b["callback_data"] for row in markup["inline_keyboard"] for b in row}


async def _enabled() -> bool:
    from app.services.sales_status import are_sales_enabled

    async with async_session_maker() as session:
        return await are_sales_enabled(session)


@pytest.mark.asyncio
async def test_financial_menu_shows_sales_status_to_a_full_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin"))
    assert _buttons(_last_screen(fake_session))["🛑 Sales Status"] == "adm:fin:sales"


@pytest.mark.asyncio
async def test_financial_menu_hides_sales_status_from_a_sales_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_admin(881, "sales")
    await dispatcher.feed_update(bot, make_callback_update(881, "adm:fin"))
    assert "🛑 Sales Status" not in _buttons(_last_screen(fake_session))


@pytest.mark.asyncio
async def test_a_sales_admin_cannot_switch_sales_off(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_admin(882, "sales")
    await dispatcher.feed_update(bot, make_callback_update(882, "adm:fin:sales:set:off"))
    assert await _enabled() is True
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True


@pytest.mark.asyncio
async def test_status_screen_defaults(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales"))
    screen = _last_screen(fake_session)
    assert "State: 🟢 Sales enabled" in screen["text"]
    assert screen["text"].count("(default)") == 2
    buttons = _buttons(screen)
    assert buttons["🔴 Disable Sales"] == "adm:fin:sales:set:off"
    assert buttons["✏️ Edit Message (FA)"] == "adm:fin:sales:msg:fa"
    assert buttons["✏️ Edit Message (EN)"] == "adm:fin:sales:msg:en"
    assert buttons["↩️ Reset Messages to Default"] == "adm:fin:sales:reset"
    assert buttons["⬅️ Back to Financial"] == "adm:fin"


@pytest.mark.asyncio
async def test_disabling_and_enabling_persist_and_rerender(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:off"))
    assert await _enabled() is False
    screen = _last_screen(fake_session)
    assert "State: 🔴 Sales disabled" in screen["text"]
    assert _buttons(screen)["🟢 Enable Sales"] == "adm:fin:sales:set:on"

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:on"))
    assert await _enabled() is True


@pytest.mark.asyncio
async def test_the_change_is_logged_with_state_and_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "-1004466777356")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:off", username="boss"))

    topics = [c for c in fake_session.calls if c[0] == "createForumTopic"]
    assert topics and topics[-1][1]["name"] == "🛠 Admin Actions"
    logged = [c for c in fake_session.calls if c[0] == "sendMessage" and "SALES STATUS" in c[1]["text"]]
    assert len(logged) == 1
    text = logged[0][1]["text"]
    assert "🛑 <b>SALES STATUS</b>" in text
    assert "State: 🔴 DISABLED" in text
    assert f"Admin: @boss ({FAKE_ADMIN_ID})" in text
    assert "Time: " in text


@pytest.mark.asyncio
async def test_a_stale_button_that_changes_nothing_logs_nothing(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two admins, one old keyboard: a second 'Disable' must not flip
    sales back on, and must not post a second entry."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "-1004466777356")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:off"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:off"))

    assert await _enabled() is False
    logged = [c for c in fake_session.calls if c[0] == "sendMessage" and "SALES STATUS" in c[1]["text"]]
    assert len(logged) == 1


@pytest.mark.asyncio
async def test_editing_the_persian_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.sales_status import get_custom_paused_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:msg:fa"))
    prompt = _last_screen(fake_session)
    assert "Persian" in prompt["text"]
    assert _buttons(prompt)["❌ Cancel"] == "adm:fin:sales"

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "  فروش تا فردا بسته است  "))

    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "fa") == "فروش تا فردا بسته است"
        assert await get_custom_paused_message(session, "en") is None
    screen = _last_screen(fake_session)
    assert "✅ Persian message saved." in screen["text"]
    assert "(custom)" in screen["text"] and "(default)" in screen["text"]


@pytest.mark.asyncio
async def test_an_oversized_message_is_refused_and_the_prompt_stays_open(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.sales_status import get_custom_paused_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:msg:en"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "x" * 3501))
    assert "3500" in _last_screen(fake_session)["text"]

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "Closed today"))
    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "en") == "Closed today"


@pytest.mark.asyncio
async def test_an_empty_message_is_refused(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.sales_status import get_custom_paused_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:msg:en"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "   "))
    assert "non-empty" in _last_screen(fake_session)["text"]
    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "en") is None


@pytest.mark.asyncio
async def test_cancel_leaves_the_edit(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.sales_status import get_custom_paused_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:msg:en"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "should not be stored"))
    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "en") is None


@pytest.mark.asyncio
async def test_reset_restores_both_defaults(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.sales_status import get_custom_paused_message, set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "fa", "الف")
        await set_custom_paused_message(session, "en", "A")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:reset"))

    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "fa") is None
        assert await get_custom_paused_message(session, "en") is None
    assert _last_screen(fake_session)["text"].count("(default)") == 2
```

In `tests/functional/test_i18n_leak.py`, add `"admin_sales.py",` to `_ADMIN_MODULES` (after `"admin_renew.py",`).

- [ ] **Step 2: Run to verify failure**

Run: rebuild, then `$T exec -T test-runner python -m pytest tests/functional/test_admin_sales.py tests/functional/test_i18n_leak.py -v`
Expected: FAIL. The new screens don't exist yet, and `test_i18n_leak` fails with "expected admin handler module not found".

- [ ] **Step 3: Add the log event**

In `app/services/adminlog.py`, after `OWNERSHIP = "ownership"`:

```python
SALES_STATUS = "sales_status"
```

After `TOPIC_ACCOUNTS = "accounts"`:

```python
TOPIC_ADMIN_ACTIONS = "admin_actions"
```

As the last entry of `EVENTS`:

```python
    SALES_STATUS: EventType(
        SALES_STATUS, "🛑", "SALES STATUS", ("State", "Admin"), TOPIC_ADMIN_ACTIONS, "🛠 Admin Actions"
    ),
```

- [ ] **Step 4: Keyboards and states**

`app/bot/keyboards/admin_sales.py`:

```python
"""Keyboards for Financial → Sales Status.

The switch button names the state it SETS, never "toggle": a stale
keyboard tapped after another admin already disabled sales must not
quietly turn them back on."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def sales_status_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if enabled:
        builder.button(text="🔴 Disable Sales", callback_data="adm:fin:sales:set:off")
    else:
        builder.button(text="🟢 Enable Sales", callback_data="adm:fin:sales:set:on")
    builder.button(text="✏️ Edit Message (FA)", callback_data="adm:fin:sales:msg:fa")
    builder.button(text="✏️ Edit Message (EN)", callback_data="adm:fin:sales:msg:en")
    builder.button(text="↩️ Reset Messages to Default", callback_data="adm:fin:sales:reset")
    builder.button(text="⬅️ Back to Financial", callback_data="adm:fin")
    builder.adjust(1)
    return builder.as_markup()


def sales_message_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:fin:sales")
    builder.adjust(1)
    return builder.as_markup()
```

`app/bot/states/admin_sales.py`:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EditSalesMessageStates(StatesGroup):
    #: The language being edited travels in the FSM data as "lang".
    text = State()
```

- [ ] **Step 5: The admin router**

`app/bot/handlers/admin_sales.py`:

```python
"""Financial → Sales Status: the switch that pauses every new sale
(purchase, renewal, trial) and the message customers see meanwhile.

Full admins only, English only. The switch lives in
app/services/sales_status.py; the customer-side check is
app/bot/sales_gate.py."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin import back_to_financial_keyboard
from app.bot.keyboards.admin_sales import sales_message_cancel_keyboard, sales_status_keyboard
from app.bot.states.admin_sales import EditSalesMessageStates
from app.db.session import async_session_maker
from app.services.adminlog import SALES_STATUS, log_event
from app.services.sales_status import (
    MAX_PAUSED_MESSAGE_LENGTH,
    MESSAGE_LANGUAGES,
    are_sales_enabled,
    clear_custom_paused_messages,
    default_paused_message,
    get_custom_paused_message,
    set_custom_paused_message,
    set_sales_enabled,
)

router = Router(name="admin_sales")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

_PREVIEW_LIMIT = 200
_LANG_NAMES = {"fa": "Persian", "en": "English"}
_LANG_FLAGS = {"fa": "🇮🇷 FA", "en": "🇬🇧 EN"}
_EMPTY_TEXT = "⚠️ Send a non-empty message, or cancel."
_TOO_LONG_TEXT = f"⚠️ That is too long — keep it under {MAX_PAUSED_MESSAGE_LENGTH} characters, or cancel."
_LOST_CONTEXT_TEXT = "⚠️ Something went wrong — please start again."


async def _preview(session: AsyncSession, lang: str) -> str:
    custom = await get_custom_paused_message(session, lang)
    if custom is None:
        # The default is short, fixed and already valid HTML: shown whole.
        return f"{_LANG_FLAGS[lang]} (default):\n{default_paused_message(lang)}"
    clipped = custom if len(custom) <= _PREVIEW_LIMIT else f"{custom[:_PREVIEW_LIMIT]}…"
    return f"{_LANG_FLAGS[lang]} (custom):\n{html.escape(clipped)}"


async def _status(session: AsyncSession) -> tuple[str, bool]:
    enabled = await are_sales_enabled(session)
    state_line = "🟢 Sales enabled" if enabled else "🔴 Sales disabled"
    lines = [
        "🛑 <b>Sales Status</b>",
        "",
        f"State: {state_line}",
        "",
        "Message shown to customers while disabled:",
        "",
        await _preview(session, "fa"),
        "",
        await _preview(session, "en"),
    ]
    return "\n".join(lines), enabled


def _who(user: User) -> str:
    return f"@{user.username} ({user.id})" if user.username else str(user.id)


async def _render(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        text, enabled = await _status(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=sales_status_keyboard(enabled=enabled))


@router.callback_query(F.data == "adm:fin:sales")
async def sales_status_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _render(callback)
    await callback.answer()


@router.callback_query(F.data.in_({"adm:fin:sales:set:off", "adm:fin:sales:set:on"}))
async def sales_set_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    enable = callback.data.endswith(":on")
    async with async_session_maker() as session:
        changed = await are_sales_enabled(session) != enable
        if changed:
            await set_sales_enabled(session, enable)
    if changed:
        await log_event(
            callback.bot, SALES_STATUS,
            State="🟢 ENABLED" if enable else "🔴 DISABLED", Admin=_who(callback.from_user),
        )
    await _render(callback)
    await callback.answer()


@router.callback_query(F.data.in_({"adm:fin:sales:msg:fa", "adm:fin:sales:msg:en"}))
async def sales_message_prompt_cb(callback: CallbackQuery, state: FSMContext) -> None:
    lang = callback.data.rsplit(":", 1)[-1]
    await state.set_state(EditSalesMessageStates.text)
    await state.update_data(lang=lang)
    if callback.message is not None:
        await callback.message.edit_text(
            f"✏️ Send the <b>{_LANG_NAMES[lang]}</b> message customers will see while sales are "
            f"disabled. Plain text, up to {MAX_PAUSED_MESSAGE_LENGTH} characters.",
            reply_markup=sales_message_cancel_keyboard(),
        )
    await callback.answer()


@router.message(EditSalesMessageStates.text)
async def sales_message_receive(message: Message, state: FSMContext) -> None:
    lang = (await state.get_data()).get("lang")
    if lang not in MESSAGE_LANGUAGES:
        await state.clear()
        await message.answer(_LOST_CONTEXT_TEXT, reply_markup=back_to_financial_keyboard())
        return

    value = (message.text or "").strip()
    if not value:
        await message.answer(_EMPTY_TEXT, reply_markup=sales_message_cancel_keyboard())
        return
    if len(value) > MAX_PAUSED_MESSAGE_LENGTH:
        await message.answer(_TOO_LONG_TEXT, reply_markup=sales_message_cancel_keyboard())
        return

    async with async_session_maker() as session:
        await set_custom_paused_message(session, lang, value)
        text, enabled = await _status(session)
    await state.clear()
    await message.answer(
        f"✅ {_LANG_NAMES[lang]} message saved.\n\n{text}", reply_markup=sales_status_keyboard(enabled=enabled)
    )


@router.callback_query(F.data == "adm:fin:sales:reset")
async def sales_message_reset_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        await clear_custom_paused_messages(session)
    await _render(callback)
    await callback.answer("Messages reset to default.")
```

- [ ] **Step 6: Menu button and router registration**

In `app/bot/keyboards/admin.py` `admin_financial_menu`, make `🛑 Sales Status` the first button inside the `if is_full_admin:` branch:

```python
    if is_full_admin:
        builder.button(text="🛑 Sales Status", callback_data="adm:fin:sales")
        builder.button(text="💳 Crypto Settlement Address", callback_data="adm:settings:crypto")
```

In `app/main.py`, add `admin_sales` to the `from app.bot.handlers import (...)` list, and register it right after `admin_settings`. It must come before `admin_fallback`:

```python
    dp.include_router(admin_settings.router)
    dp.include_router(admin_sales.router)
```

- [ ] **Step 7: Run to verify pass**

Run: rebuild, then `$T exec -T test-runner python -m pytest tests/functional/test_admin_sales.py tests/functional/test_i18n_leak.py tests/functional/test_admin_financial_menu.py tests/functional/test_adminlog.py tests/functional/test_log_topics_and_reports.py -v`
Expected: all PASS.

- [ ] **Step 8: CLAUDE.md**

Add this bullet to the Architecture list, right after the `app/services/adminlog.py` bullet:

```markdown
- Sales switch (`app/services/sales_status.py` + `app/bot/sales_gate.py`,
  admin screen Financial → 🛑 Sales Status, full admins only): the ONE
  on/off for new sales, `app_config` key `sales_enabled` (absent =
  enabled). `block_if_sales_paused` runs first in exactly six handlers -
  `buy:plan`, `buy:confirm`, `renew:plan`, `renew:confirm`, `menu:trial`,
  `trial:confirm` - so menus stay browsable and the block lands on
  selection. Never gate payment confirmation or the reconciler: an
  invoice already paid is always honored. The admin buttons SET a state
  (`adm:fin:sales:set:on|off`), never toggle, so a stale keyboard can't
  flip sales back on; each real change posts `SALES_STATUS` to the
  🛠 Admin Actions topic.
```

- [ ] **Step 9: Commit**

```bash
git add app/services/adminlog.py app/bot/keyboards/admin_sales.py app/bot/states/admin_sales.py app/bot/handlers/admin_sales.py app/bot/keyboards/admin.py app/main.py tests/functional/test_admin_sales.py tests/functional/test_i18n_leak.py CLAUDE.md
git commit -m "feat: Sales Status admin screen with logged on/off switch"
```

---

### Task 4: Full suite

- [ ] **Step 1: Run everything**

Run: `make test`
Expected: the whole suite passes, with 0 failures and 0 errors. A failure anywhere, including in a test that looks unrelated, blocks completion. Fix the cause, never the assertion.

- [ ] **Step 2: Tear down**

Run: `make test-down`
