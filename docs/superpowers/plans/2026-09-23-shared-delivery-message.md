# Shared Account Delivery Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One delivery message for all three account-handover flows (purchase, renewal, trial), differing only by headline, built in one place.

**Architecture:** A new `app/services/delivery.py` owns the message. `confirmation.py` (purchase and renewal) and `trial.py` both call it and pass their own field sources, so neither builds text.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, pytest in the isolated Docker stack.

**Spec:** `docs/superpowers/specs/2026-09-23-shared-delivery-message-design.md`

## Global Constraints

- Customer text goes through `t(key, lang)` in both `fa` and `en`; no literals in services or handlers.
- HTML parse mode: labels `<b>`, each credential its own `<code>` span.
- `data_cap_mb` is always passed in by the caller — the payment's snapshot for paid orders, the trial plan's value for a trial. The delivery function never re-derives it.
- Buttons reuse `menu:tutorials` and `menu:root`; no new callbacks.
- English pluralises the day word; Persian does not inflect.
- Async only, type hints on every signature, thin handlers.
- Run the suite with `make test`, or against the running stack: `docker exec homeland_bot_test-test-runner-1 sh -c 'rm -rf /app/app /app/tests'`, `tar --exclude=.git --exclude=.claude -cf - app tests | docker exec -i homeland_bot_test-test-runner-1 tar -xf - -C /app`, `docker exec homeland_bot_test-db_test-1 psql -U homeland_test -d homeland_test -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`, then `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/ -q`.

---

## File Structure

- **Create** `app/services/delivery.py` — `PURCHASE`/`RENEWAL`/`TRIAL`, `send_account_delivery`.
- **Modify** `app/i18n/texts.py` — add three headline keys, `delivery_body`, `delivery_body_no_password`, `day_singular`, `day_plural`; remove `order_delivered`, `order_delivered_no_password`, `trial_ready`, `trial_credentials_unavailable`.
- **Modify** `app/services/payments/confirmation.py` — call the shared function; delete its own builder.
- **Modify** `app/bot/handlers/trial.py` — `_send_trial_credentials` calls the shared function.
- **Modify** `tests/functional/test_payment_recovery.py`, `test_trial_flow.py`, `test_webhook.py`, `test_i18n.py`.

---

## Task 1: The shared delivery service

**Files:**
- Create: `app/services/delivery.py`
- Modify: `app/i18n/texts.py`
- Test: `tests/functional/test_delivery_message.py`

**Interfaces:**
- Produces: `PURCHASE`, `RENEWAL`, `TRIAL`; `async send_account_delivery(bot, telegram_id, *, kind: str, plan: Plan | None, data_cap_mb: int, username: str, password: str | None, lang: str) -> None`.

- [ ] **Step 1: Write the failing unit-level tests**

`tests/functional/test_delivery_message.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.fakes.fake_bot_session import FakeBotSession


async def _plan(seeded_catalog: dict, *, category: str, name: str):  # type: ignore[no-untyped-def]
    from app.services.catalog import get_plan

    plan_id = next(
        p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name
    )
    async with async_session_maker() as session:
        return await get_plan(session, plan_id)


def _last_message(fake_session: FakeBotSession) -> dict[str, Any]:
    return [c for c in fake_session.calls if c[0] == "sendMessage"][-1][1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "headline"),
    [
        ("purchase", "Your order has been placed successfully"),
        ("renewal", "Your renewal was successful"),
        ("trial", "Your trial service is ready"),
    ],
)
async def test_every_flow_sends_the_same_body_under_its_own_headline(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, kind: str, headline: str
) -> None:
    from app.services.delivery import send_account_delivery

    plan = await _plan(seeded_catalog, category="scroll", name="1 Month")
    await send_account_delivery(
        bot, 3001, kind=kind, plan=plan, data_cap_mb=10240,
        username="ir.abc123", password="pw1234", lang="en",
    )

    payload = _last_message(fake_session)
    text = payload["text"]
    assert headline in text
    # The body is identical whatever the flow.
    assert "<b>Plan:</b> 1 Month" in text
    assert "30 days from first connection" in text
    assert "<b>Volume:</b> 10 GB" in text
    assert "<code>ir.abc123</code>" in text
    assert "<code>pw1234</code>" in text
    assert "Tutorial section of the main menu" in text

    buttons = {b["text"]: b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row}
    assert buttons["📘 Tutorial"] == "menu:tutorials"
    assert buttons["🔙 Back to Main Menu"] == "menu:root"


@pytest.mark.asyncio
async def test_one_day_is_singular_and_many_are_plural(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """A trial lasts one day; "1 days from first connection" is wrong."""
    from app.services.delivery import TRIAL, send_account_delivery

    trial = await _plan(seeded_catalog, category="trial", name="Trial")
    await send_account_delivery(
        bot, 3002, kind=TRIAL, plan=trial, data_cap_mb=trial.data_cap_mb,
        username="ir.t00001", password="pw", lang="en",
    )
    assert "1 day from first connection" in _last_message(fake_session)["text"]

    monthly = await _plan(seeded_catalog, category="scroll", name="1 Month")
    await send_account_delivery(
        bot, 3002, kind="purchase", plan=monthly, data_cap_mb=10240,
        username="ir.m00001", password="pw", lang="en",
    )
    assert "30 days from first connection" in _last_message(fake_session)["text"]


@pytest.mark.asyncio
async def test_trial_fields_come_from_the_trial_plan(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Verified against the seeded catalog rather than assumed: the trial
    is a real Plan row (1 day, 1024 MB)."""
    from app.services.delivery import TRIAL, send_account_delivery

    trial = await _plan(seeded_catalog, category="trial", name="Trial")
    await send_account_delivery(
        bot, 3003, kind=TRIAL, plan=trial, data_cap_mb=trial.data_cap_mb,
        username="ir.t00002", password="pw", lang="en",
    )

    text = _last_message(fake_session)["text"]
    assert "<b>Plan:</b> Trial" in text
    assert "1 day from first connection" in text
    assert "<b>Volume:</b> 1 GB" in text


@pytest.mark.asyncio
async def test_persian_rendering(bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.delivery import TRIAL, send_account_delivery

    trial = await _plan(seeded_catalog, category="trial", name="Trial")
    await send_account_delivery(
        bot, 3004, kind=TRIAL, plan=trial, data_cap_mb=trial.data_cap_mb,
        username="ir.t00003", password="pw", lang="fa",
    )

    payload = _last_message(fake_session)
    text = payload["text"]
    assert "سرویس تست شما آماده است" in text
    assert "روز از زمان اولین اتصال" in text
    assert "یوزرنیم:" in text and "پسورد:" in text
    buttons = {b["text"] for row in payload["reply_markup"]["inline_keyboard"] for b in row}
    assert "📘 آموزش" in buttons and "🔙 بازگشت به منوی اصلی" in buttons


@pytest.mark.asyncio
async def test_missing_password_still_delivers_with_the_username(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.delivery import send_account_delivery

    plan = await _plan(seeded_catalog, category="scroll", name="1 Month")
    await send_account_delivery(
        bot, 3005, kind="purchase", plan=plan, data_cap_mb=10240,
        username="ir.nopass", password=None, lang="en",
    )

    text = _last_message(fake_session)["text"]
    assert "contact support" in text.lower()
    assert "<code>ir.nopass</code>" in text
    assert "Your order has been placed successfully" in text


@pytest.mark.asyncio
async def test_unlimited_volume_label(bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.delivery import send_account_delivery

    plan = await _plan(seeded_catalog, category="scroll", name="1 Month")
    await send_account_delivery(
        bot, 3006, kind="purchase", plan=plan, data_cap_mb=0,
        username="ir.unl", password="pw", lang="en",
    )
    assert "<b>Volume:</b> Unlimited" in _last_message(fake_session)["text"]


@pytest.mark.asyncio
async def test_a_blocked_bot_never_raises(bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    """The account is provisioned either way - a blocked bot must not
    turn into a failure the caller has to handle."""
    from aiogram.exceptions import TelegramForbiddenError

    from app.services.delivery import send_account_delivery

    plan = await _plan(seeded_catalog, category="scroll", name="1 Month")
    fake_session.blocked_chat_ids.add(3007)
    try:
        await send_account_delivery(
            bot, 3007, kind="purchase", plan=plan, data_cap_mb=10240,
            username="ir.blocked", password="pw", lang="en",
        )
    except TelegramForbiddenError:  # pragma: no cover
        pytest.fail("a blocked bot must be swallowed")
```

Check `tests/fakes/fake_bot_session.py` for the exact attribute that simulates a blocked chat and adapt the last test to it.

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_delivery_message.py -q`
Expected: FAIL with `ModuleNotFoundError: app.services.delivery`.

- [ ] **Step 3: Add the i18n keys**

Remove `order_delivered`, `order_delivered_no_password`, `trial_ready`, `trial_credentials_unavailable` from both blocks. Add to `en`:

```python
        "delivery_headline_purchase": "🎉 Your order has been placed successfully.",
        "delivery_headline_renewal": "🎉 Your renewal was successful.",
        "delivery_headline_trial": "🎉 Your trial service is ready.",
        "day_singular": "day",
        "day_plural": "days",
        "delivery_body": (
            "<b>Plan:</b> {plan}\n"
            "<b>Duration:</b> {days} {day_word} from first connection\n"
            "<b>Volume:</b> {volume}\n\n"
            "<b>Username:</b> <code>{username}</code>\n"
            "<b>Password:</b> <code>{password}</code>\n\n"
            "Setup instructions and connection details for different platforms and "
            "protocols are available in the Tutorial section of the main menu."
        ),
        "delivery_body_no_password": (
            "<b>Plan:</b> {plan}\n"
            "<b>Duration:</b> {days} {day_word} from first connection\n"
            "<b>Volume:</b> {volume}\n\n"
            "<b>Username:</b> <code>{username}</code>\n"
            "<b>Password:</b> unavailable — please contact support\n\n"
            "Setup instructions and connection details for different platforms and "
            "protocols are available in the Tutorial section of the main menu."
        ),
```

and to `fa` (روز for both day words, since Persian does not inflect):

```python
        "delivery_headline_purchase": "🎉 سفارش شما با موفقیت ثبت شد.",
        "delivery_headline_renewal": "🎉 تمدید شما با موفقیت انجام شد.",
        "delivery_headline_trial": "🎉 سرویس تست شما آماده است.",
        "day_singular": "روز",
        "day_plural": "روز",
        "delivery_body": (
            "<b>پلن خریداری‌شده:</b> {plan}\n"
            "<b>مدت زمان استفاده:</b> {days} {day_word} از زمان اولین اتصال\n"
            "<b>حجم:</b> {volume}\n\n"
            "<b>یوزرنیم:</b> <code>{username}</code>\n"
            "<b>پسورد:</b> <code>{password}</code>\n\n"
            "آموزش تنظیمات و اطلاعات اتصال برای پلتفرم‌ها و پروتکل‌های مختلف را "
            "می‌توانید از بخش «آموزش» در منوی اصلی دریافت کنید."
        ),
        "delivery_body_no_password": (
            "<b>پلن خریداری‌شده:</b> {plan}\n"
            "<b>مدت زمان استفاده:</b> {days} {day_word} از زمان اولین اتصال\n"
            "<b>حجم:</b> {volume}\n\n"
            "<b>یوزرنیم:</b> <code>{username}</code>\n"
            "<b>پسورد:</b> در دسترس نیست — لطفاً با پشتیبانی تماس بگیرید\n\n"
            "آموزش تنظیمات و اطلاعات اتصال برای پلتفرم‌ها و پروتکل‌های مختلف را "
            "می‌توانید از بخش «آموزش» در منوی اصلی دریافت کنید."
        ),
```

- [ ] **Step 4: Write the service**

`app/services/delivery.py`:

```python
"""The ONE account-delivery message.

Three flows hand a customer a working account - a new purchase, a
renewal, and a free trial - and every one of them sends this. Only the
headline differs; the body, the credential formatting and the two
buttons are identical, so there is a single template per language to
keep correct rather than three that drift.
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
    *, kind: str, plan: Plan | None, data_cap_mb: int, username: str, password: str | None, lang: str,
    fallback_plan_name: str = "—",
) -> str:
    """Headline + shared body. Separated from sending so a test can read
    the text without a Bot, and so a future caller can embed it."""
    headline = t(_HEADLINE_KEYS.get(kind, _HEADLINE_KEYS[PURCHASE]), lang)
    days = plan.duration_days if plan is not None else 0
    fields = {
        "plan": plan_display_name(plan, lang) if plan is not None else fallback_plan_name,
        "days": days,
        "day_word": t("day_singular" if days == 1 else "day_plural", lang),
        "volume": format_data_cap(data_cap_mb, lang),
        "username": username,
    }
    if password:
        body = t("delivery_body", lang, password=password, **fields)
    else:
        body = t("delivery_body_no_password", lang, **fields)
    return f"{headline}\n\n{body}"


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
) -> None:
    """`data_cap_mb` is passed in rather than read off `plan` on purpose:
    a paid order delivers the snapshot stored on its payment, so an admin
    editing the catalog mid-purchase cannot change what that buyer was
    sold, while a trial passes the trial plan's own value."""
    text = build_delivery_text(
        kind=kind, plan=plan, data_cap_mb=data_cap_mb, username=username,
        password=password, lang=lang, fallback_plan_name=fallback_plan_name,
    )
    try:
        await bot.send_message(telegram_id, text, reply_markup=order_delivered_keyboard(lang))
    except TelegramForbiddenError:
        # The account IS provisioned; the customer has merely blocked the
        # bot. Never let that look like a delivery failure upstream.
        logger.warning(
            "Delivery message not sent to %s (%s) - bot is blocked", telegram_id, kind
        )
```

- [ ] **Step 5: Run the tests**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_delivery_message.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/delivery.py app/i18n/texts.py tests/functional/test_delivery_message.py
git commit -m "feat: one shared account-delivery message for all three flows"
```

---

## Task 2: Purchase, renewal and trial call it

**Files:**
- Modify: `app/services/payments/confirmation.py`, `app/bot/handlers/trial.py`
- Test: `tests/functional/test_payment_recovery.py`, `test_webhook.py`, `test_trial_flow.py`, `test_i18n.py`

**Interfaces:**
- Consumes: `send_account_delivery`, `PURCHASE`, `RENEWAL`, `TRIAL`.

- [ ] **Step 1: Update the flow tests**

In `test_payment_recovery.py`, keep the existing delivery assertions and add one asserting a renewal shows the renewal headline. In `test_trial_flow.py`, replace assertions on the old `trial_ready` wording ("Your trial is ready", "تست رایگان شما آماده است") with the new headline and body, and replace the `trial_credentials_unavailable` assertion with the no-password body. Update `test_i18n.py`'s key count (four removed, seven added).

- [ ] **Step 2: Point confirmation.py at the shared function**

Delete `_send_delivery_message` and its `order_delivered_keyboard` / `format_data_cap` / `plan_display_name` imports. Replace the call site:

```python
    plan = await get_plan(session, payment.plan_id) if payment.plan_id is not None else None
    lang = (await get_language(session, payment.telegram_id)) or "en"
    await send_account_delivery(
        bot, payment.telegram_id,
        kind=RENEWAL if payment.purpose == "renew" else PURCHASE,
        plan=plan,
        # The snapshot on the payment, never the plan's current value.
        data_cap_mb=payment.data_cap_mb,
        username=username,
        password=await _recover_password(payment, username),
        lang=lang,
        fallback_plan_name=payment.group_name,
    )
```

`_recover_password` stays exactly as it is.

- [ ] **Step 3: Point trial.py at it**

`_send_trial_credentials` becomes:

```python
async def _send_trial_credentials(bot: Bot, telegram_id: int, lang: str) -> None:
    """The trial's credentials were generated in an earlier callback with
    nothing carried forward (no FSM state, by design - a password must
    never travel in callback_data), so they are looked up fresh: the
    just-created VPNUser row gives the username and IBSng re-reads the
    password it stored."""
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
        trial_plans = await list_plans(session, category="trial")
        plan = trial_plans[0] if trial_plans else None

    password: str | None = None
    try:
        async with IBSngClient() as client:
            password = await client.get_user_password(username=vpn_user.ibsng_username)
        if password is None:
            logger.error(
                "IBSng returned no password for just-created trial account %r (telegram_id=%s)",
                vpn_user.ibsng_username, telegram_id,
            )
    except IBSngError:
        logger.exception("Could not read the trial password back for telegram_id=%s", telegram_id)

    await send_account_delivery(
        bot, telegram_id, kind=TRIAL, plan=plan,
        data_cap_mb=vpn_user.data_cap_mb, username=vpn_user.ibsng_username,
        password=password, lang=lang,
    )
```

Delete whatever now-unused imports and helpers this leaves behind in `trial.py`.

- [ ] **Step 4: Run the suite**

Run: `make test` (or the fallback)
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "refactor: purchase, renewal and trial all deliver through one message"
```

---

## Task 3: Docs and deploy

- [ ] **Step 1: Update CLAUDE.md**

Record that `app/services/delivery.py` is the only place that builds an account-delivery message, and that all three flows call it.

- [ ] **Step 2: Deploy**

```bash
git push origin main
ssh homeland-bot-server 'cd ~/Homeland-Bot && git pull --ff-only && docker compose up -d --build && docker compose logs --tail=10 bot'
```

- [ ] **Step 3: Verify**

A free trial is the cheapest end-to-end check and needs no payment: run one from a test account and confirm the new headline, the plan line reading "Trial"/"تست رایگان", "1 day", "1 GB", both credentials tappable, and both buttons working.

---

## Self-Review

- **Spec coverage:** §2 message and headlines → Task 1 Step 3; §3 the one function → Task 1 Step 4; §4 callers → Task 2; §5 trial fields → Task 2 Step 3 plus its test; §6 password sourcing → `_recover_password` kept, trial reads back; §7 removed keys → Task 1 Step 3 and Task 2 Step 1; §8 tests → Tasks 1–2.
- **Placeholder scan:** Task 2 Step 1 describes test edits by name rather than quoting each file in full, since they are assertion swaps in existing tests; every new production code path is given in full.
- **Type consistency:** `send_account_delivery(..., kind: str, plan: Plan | None, data_cap_mb: int, username: str, password: str | None, lang: str)` matches all three call sites and every test; `build_delivery_text` takes the same keywords minus `bot`/`telegram_id`; `format_data_cap(data_cap_mb, lang)` and `plan_display_name(plan, lang)` match their existing signatures.
