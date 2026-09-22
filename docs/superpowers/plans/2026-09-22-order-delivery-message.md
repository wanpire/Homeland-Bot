# Order Delivery Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-line payment confirmation with a full bilingual delivery message carrying plan, duration, volume and tap-to-copy credentials, change the generated username prefix to `ir.`, and raise the unlimited-plan IBSng credit to 100.

**Architecture:** All three land in code that already exists. The message is built in `app/services/payments/confirmation.py`, the single path both the Plisio callback and the reconciler use, so there is one delivery message for purchases and renewals alike. The prefix and the credit are named constants in `app/services/vpn_users.py`.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, pytest in the isolated Docker stack.

**Spec:** `docs/superpowers/specs/2026-09-22-order-delivery-message-design.md`

## Global Constraints

- Customer text goes through `t(key, lang)` in both `fa` and `en`; no literals in handlers or services.
- The bot's parse mode is HTML: credentials use `<code>` spans for tap-to-copy, labels use `<b>`.
- Volume comes from `payment.data_cap_mb` (the snapshot), never the plan's current value.
- Buttons reuse `menu:tutorials` and `menu:root`; no new callbacks.
- The credit change applies **only** to the unlimited sentinel path. Metered plans keep passing their own data cap, per the review decision recorded in spec §1.
- Async only, type hints on every signature, thin handlers.
- Run the suite with `make test`, or the running stack: `docker exec homeland_bot_test-test-runner-1 sh -c 'rm -rf /app/app /app/tests'`, `tar --exclude=.git --exclude=.claude -cf - app tests | docker exec -i homeland_bot_test-test-runner-1 tar -xf - -C /app`, `docker exec homeland_bot_test-db_test-1 psql -U homeland_test -d homeland_test -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`, then `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/ -q`.

---

## File Structure

- **Modify** `app/services/vpn_users.py` — `_USERNAME_PREFIX`, `UNLIMITED_PLAN_IBSNG_CREDIT`.
- **Modify** `app/i18n/texts.py` — add `order_delivered`, `order_delivered_no_password`, `tutorial_button`, `back_to_main_menu_button`; remove `payment_confirmed`, `action_activated`, `action_renewed`.
- **Create** `app/bot/keyboards/delivery.py` — `order_delivered_keyboard(lang)`.
- **Modify** `app/services/payments/confirmation.py` — build and send the message.
- **Modify** tests: `test_payment_recovery.py`, `test_webhook.py`, `test_trial_flow.py`, `test_vpn_users.py` (or wherever provisioning is asserted), `test_i18n.py`.

---

## Task 1: Username prefix and unlimited credit

**Files:**
- Modify: `app/services/vpn_users.py`
- Test: `tests/functional/test_trial_flow.py`, provisioning tests

**Interfaces:**
- Produces: `UNLIMITED_PLAN_IBSNG_CREDIT = 100`; usernames matching `ir.<6 chars>`.

- [ ] **Step 1: Write the failing tests**

Add to the provisioning test module:

```python
@pytest.mark.asyncio
async def test_generated_usernames_use_the_ir_prefix() -> None:
    from app.services.vpn_users import generate_vpn_credentials

    username, password = generate_vpn_credentials()
    assert username.startswith("ir.")
    assert len(username) == len("ir.") + 6
    assert password


@pytest.mark.asyncio
async def test_unlimited_plan_is_provisioned_with_credit_100(ibsng_server, seeded_catalog: dict) -> None:
    """data_cap_mb=0 is Homeland's "Unlimited" sentinel and must never
    reach IBSng as credit=0, which silently produces an account that
    cannot connect."""
    from app.db.session import async_session_maker
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=2001, username=username, password=password,
            group_name="1M-1U-Iran-Unlimited", data_cap_mb=0, plan_id=None,
        )
    assert ibsng_server.created_users[username]["credit"] == 100


@pytest.mark.asyncio
async def test_metered_plan_still_passes_its_own_data_cap(ibsng_server, seeded_catalog: dict) -> None:
    """The flat credit applies only to unlimited plans - a metered plan
    that stopped sending its cap would lose per-user quota enforcement."""
    from app.db.session import async_session_maker
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=2002, username=username, password=password,
            group_name="1M-1U-Iran-10G", data_cap_mb=10240, plan_id=None,
        )
    assert ibsng_server.created_users[username]["credit"] == 10240
```

Check `tests/fakes/fake_ibsng_server.py` for how created users are recorded and adapt the accessor to whatever it exposes.

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_vpn_users.py -q`
Expected: FAIL on the `ir.` prefix and on credit 100 (today it is 10).

- [ ] **Step 3: Change the two constants**

In `app/services/vpn_users.py`:

```python
_USERNAME_PREFIX = "ir."
```

and replace the credit constant, keeping the hard-won IBSng findings in the comment:

```python
# IBSng silently accepts credit=0 but leaves the account unable to
# connect at all (confirmed via AloBot, which shares this IBSng
# instance). data_cap_mb=0 is Homeland's own display sentinel for
# "Unlimited" (see app/services/catalog.py's format_data_cap) and must
# never be forwarded as a literal credit=0, so unlimited plans get this
# flat value instead. Raised from 10 to 100 on 2026-09-22 by product
# decision; IBSng's group-level policy, not per-user credit magnitude,
# is what actually governs usage on the -Unlimited groups.
#
# Metered plans deliberately do NOT use this: they pass their own
# data_cap_mb, which is what caps the buyer. Flattening every account to
# one credit would remove that.
UNLIMITED_PLAN_IBSNG_CREDIT = 100
```

Update the single use in `create_vpn_user` to the new name.

- [ ] **Step 4: Run the tests**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_vpn_users.py tests/functional/test_trial_flow.py -q`
Expected: PASS. Fix any test that hardcoded an `hl.` username.

- [ ] **Step 5: Commit**

```bash
git add app/services/vpn_users.py tests
git commit -m "feat: ir. username prefix and credit 100 for unlimited plans"
```

---

## Task 2: The delivery message

**Files:**
- Modify: `app/i18n/texts.py`
- Create: `app/bot/keyboards/delivery.py`
- Modify: `app/services/payments/confirmation.py`
- Test: `tests/functional/test_payment_recovery.py`, `test_webhook.py`, `test_i18n.py`

**Interfaces:**
- Consumes: `plan_display_name`, `format_data_cap`, `IBSngClient.get_user_password`.
- Produces: `order_delivered_keyboard(lang) -> InlineKeyboardMarkup`; keys `order_delivered`, `order_delivered_no_password`, `tutorial_button`, `back_to_main_menu_button`.

- [ ] **Step 1: Write the failing tests**

In `tests/functional/test_payment_recovery.py`:

```python
@pytest.mark.asyncio
async def test_delivery_message_carries_the_order_details_in_english(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    payment = await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1801)

    client = await _make_client(bot)
    try:
        body = _signed_body({**REAL_CALLBACK, "order_number": str(payment.id)})
        await client.post("/webhooks/crypto?json=true", data=body, headers={"Content-Type": "application/json"})
    finally:
        await client.close()

    sent = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == 1801]
    text = sent[-1][1]["text"]
    assert "Your order has been placed successfully" in text
    assert "1 Month" in text                       # plan name
    assert "30 days from first connection" in text  # duration
    assert "10 GB" in text                          # volume, from the snapshot
    assert "<code>" in text and payment.ibsng_username in text
    assert payment.ibsng_password in text

    buttons = {b["text"]: b["callback_data"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"] for b in row}
    assert buttons["📘 Tutorial"] == "menu:tutorials"
    assert buttons["🔙 Back to Main Menu"] == "menu:root"


@pytest.mark.asyncio
async def test_delivery_message_is_persian_for_a_persian_buyer(...) -> None:
    """Set the buyer's language to fa, then assert the Persian labels and
    the same two buttons with Persian captions."""


@pytest.mark.asyncio
async def test_credentials_are_separate_code_spans(...) -> None:
    """Tap-to-copy only works per span: username and password must be in
    their own <code> spans, not one combined block."""
    assert f"<code>{username}</code>" in text
    assert f"<code>{password}</code>" in text


@pytest.mark.asyncio
async def test_unlimited_plan_renders_volume_as_unlimited(...) -> None:
    """A plan with data_cap_mb=0 must read "Unlimited", never "0 MB"."""


@pytest.mark.asyncio
async def test_renewal_reads_the_password_back_from_ibsng(...) -> None:
    """A renewal payment carries no password - the account keeps its
    own - so it is read back the way the trial flow does."""


@pytest.mark.asyncio
async def test_missing_password_still_delivers_the_order(...) -> None:
    """The service IS provisioned; an unreadable password must degrade to
    the contact-support variant, never look like a failed order."""
    monkeypatch IBSngClient.get_user_password to return None
    assert "contact support" in text.lower()
    assert payment.ibsng_username in text
```

Update `tests/functional/test_i18n.py`'s key count (three keys removed, four added).

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_payment_recovery.py -q`
Expected: FAIL — the old one-line message is still sent.

- [ ] **Step 3: Add the i18n keys**

Remove `payment_confirmed`, `action_activated`, `action_renewed` from both blocks. Add to `en`:

```python
        "order_delivered": (
            "🎉 Your order has been placed successfully.\n\n"
            "<b>Plan:</b> {plan}\n"
            "<b>Duration:</b> {days} days from first connection\n"
            "<b>Volume:</b> {volume}\n\n"
            "<b>Username:</b> <code>{username}</code>\n"
            "<b>Password:</b> <code>{password}</code>\n\n"
            "Setup instructions and connection details for different platforms and "
            "protocols are available in the Tutorial section of the main menu."
        ),
        "order_delivered_no_password": (
            "🎉 Your order has been placed successfully.\n\n"
            "<b>Plan:</b> {plan}\n"
            "<b>Duration:</b> {days} days from first connection\n"
            "<b>Volume:</b> {volume}\n\n"
            "<b>Username:</b> <code>{username}</code>\n"
            "<b>Password:</b> unavailable — please contact support\n\n"
            "Setup instructions and connection details for different platforms and "
            "protocols are available in the Tutorial section of the main menu."
        ),
        "tutorial_button": "📘 Tutorial",
        "back_to_main_menu_button": "🔙 Back to Main Menu",
```

and to `fa`:

```python
        "order_delivered": (
            "🎉 سفارش شما با موفقیت ثبت شد.\n\n"
            "<b>پلن خریداری‌شده:</b> {plan}\n"
            "<b>مدت زمان استفاده:</b> {days} روز از زمان اولین اتصال\n"
            "<b>حجم:</b> {volume}\n\n"
            "<b>یوزرنیم:</b> <code>{username}</code>\n"
            "<b>پسورد:</b> <code>{password}</code>\n\n"
            "آموزش تنظیمات و اطلاعات اتصال برای پلتفرم‌ها و پروتکل‌های مختلف را "
            "می‌توانید از بخش «آموزش» در منوی اصلی دریافت کنید."
        ),
        "order_delivered_no_password": (
            "🎉 سفارش شما با موفقیت ثبت شد.\n\n"
            "<b>پلن خریداری‌شده:</b> {plan}\n"
            "<b>مدت زمان استفاده:</b> {days} روز از زمان اولین اتصال\n"
            "<b>حجم:</b> {volume}\n\n"
            "<b>یوزرنیم:</b> <code>{username}</code>\n"
            "<b>پسورد:</b> در دسترس نیست — لطفاً با پشتیبانی تماس بگیرید\n\n"
            "آموزش تنظیمات و اطلاعات اتصال برای پلتفرم‌ها و پروتکل‌های مختلف را "
            "می‌توانید از بخش «آموزش» در منوی اصلی دریافت کنید."
        ),
        "tutorial_button": "📘 آموزش",
        "back_to_main_menu_button": "🔙 بازگشت به منوی اصلی",
```

- [ ] **Step 4: Add the keyboard**

`app/bot/keyboards/delivery.py`:

```python
"""The keyboard under a delivered order. Both destinations are the main
menu's own callbacks - a delivered order should lead straight into the
setup guides, not into a flow of its own."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t


def order_delivered_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("tutorial_button", lang), callback_data="menu:tutorials")
    builder.button(text=t("back_to_main_menu_button", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Build and send it**

In `app/services/payments/confirmation.py`, replace the notification block with a call to a new helper, and add the helper:

```python
async def _send_delivery_message(bot: Bot, session: AsyncSession, payment: Payment, username: str) -> None:
    """The one message a buyer gets for a completed order, purchase and
    renewal alike."""
    lang = (await get_language(session, payment.telegram_id)) or "en"
    plan = await get_plan(session, payment.plan_id) if payment.plan_id is not None else None
    password = await _recover_password(payment, username)

    fields = {
        "plan": plan_display_name(plan, lang) if plan is not None else payment.group_name,
        "days": plan.duration_days if plan is not None else "—",
        # The snapshot on the payment, not the plan's current value: an
        # admin editing the catalog mid-payment must not change what this
        # buyer was sold.
        "volume": format_data_cap(payment.data_cap_mb, lang),
        "username": username,
    }
    key = "order_delivered" if password else "order_delivered_no_password"
    text = t(key, lang, **fields, password=password) if password else t(key, lang, **fields)

    try:
        await bot.send_message(payment.telegram_id, text, reply_markup=order_delivered_keyboard(lang))
    except TelegramForbiddenError:
        logger.warning(
            "Payment %s: activated but could not notify user %s - bot is blocked",
            payment.id, payment.telegram_id,
        )


async def _recover_password(payment: Payment, username: str) -> str | None:
    """A purchase carries its generated password; a renewal does not,
    because the account keeps the one it has, so it is read back from
    IBSng exactly as the trial flow does. A failure here must never fail
    the order - the service is already provisioned."""
    if payment.ibsng_password:
        return payment.ibsng_password
    try:
        async with IBSngClient() as client:
            return await client.get_user_password(username=username)
    except IBSngError:
        logger.warning("Payment %s: could not read the password back for %s", payment.id, username)
        return None
```

- [ ] **Step 6: Run the tests**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_payment_recovery.py tests/functional/test_webhook.py tests/functional/test_i18n.py -q`
Expected: PASS.

- [ ] **Step 7: Full suite and commit**

Run: `make test` (or the fallback)

```bash
git add app tests
git commit -m "feat: full order delivery message with credentials and setup buttons"
```

---

## Task 3: Docs and deploy

- [ ] **Step 1: Update CLAUDE.md and commit**

Add a line recording that `confirm_paid_payment` sends the single delivery message for purchases and renewals, and that the unlimited-plan credit is a named constant.

- [ ] **Step 2: Deploy**

```bash
git push origin main
ssh homeland-bot-server 'cd ~/Homeland-Bot && git pull --ff-only && docker compose up -d --build && docker compose logs --tail=10 bot'
```

- [ ] **Step 3: Verify**

The next real purchase should show the new message. Until one happens, confirm on the server that a freshly generated username starts with `ir.` and that the constant reads 100.

---

## Self-Review

- **Spec coverage:** §2 message → Task 2 Steps 3–5; §3 single send path → Task 2 Step 5; §4 password sources → `_recover_password`; §5 prefix → Task 1; §6 credit → Task 1; §7 tests → Tasks 1–2.
- **Placeholder scan:** Task 2 Step 1 sketches four test bodies by intent rather than in full; each names its exact assertion. Every production-code step carries real code.
- **Type consistency:** `order_delivered_keyboard(lang: str)` matches its use; `_recover_password(payment, username) -> str | None` matches the `key` selection above it; `format_data_cap(data_cap_mb: int, lang: str)` and `plan_display_name(plan, lang)` match their existing signatures.
