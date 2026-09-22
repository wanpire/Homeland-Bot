# Post-Delivery OpenVPN Setup Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After any account handover, send the `.ovpn` config and let the customer pick their device, sending only that platform's download link, and stop emitting the "guide is not ready" placeholder in delivery flows.

**Architecture:** One service function and one router own the step; purchase, renewal, trial and My Services all call it. The guide lookup is dropped from delivery flows and stays in Tutorials, where a missing guide is worth reporting.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, pytest in the isolated Docker stack.

**Spec:** `docs/superpowers/specs/2026-09-23-openvpn-setup-step-design.md`

## Global Constraints

- Customer text goes through `t(key, lang)` in `fa` and `en`; platform labels come from the catalog and are not translated.
- The `.ovpn` profile's generation and naming are untouched: this task only changes how links and surrounding messages are presented.
- Every flow calls one shared function; no flow builds this material itself.
- `guide_not_ready` must remain reachable from Tutorials and unreachable from delivery flows.
- Async only, type hints on every signature, thin handlers, no new callback roots beyond `ovpn:*`.
- Run the suite with `make test`, or against the running stack: `docker exec homeland_bot_test-test-runner-1 sh -c 'rm -rf /app/app /app/tests'`, `tar --exclude=.git --exclude=.claude -cf - app tests | docker exec -i homeland_bot_test-test-runner-1 tar -xf - -C /app`, `docker exec homeland_bot_test-db_test-1 psql -U homeland_test -d homeland_test -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`, then `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/ -q`.

---

## File Structure

- **Create** `app/services/openvpn_setup.py` — `send_openvpn_setup`.
- **Create** `app/bot/keyboards/openvpn_setup.py` — `openvpn_platform_keyboard`.
- **Create** `app/bot/handlers/openvpn_setup.py` — the `ovpn:*` router.
- **Modify** `app/services/tutorial_delivery.py` — `send_guide(..., notify_if_missing)`, `deliver_setup` passes `False`.
- **Modify** `app/services/payments/confirmation.py` — call the step after the credentials message.
- **Modify** `app/bot/handlers/trial.py`, `app/bot/handlers/myservices.py` — OpenVPN branches call the step.
- **Modify** `app/main.py` — register the router.
- **Modify** `app/i18n/texts.py` — two new keys.
- **Create** `tests/functional/test_openvpn_setup.py`; modify `test_trial_flow.py`, `test_myservices_flow.py`, `test_tutorials_flow.py`, `test_i18n.py`.

---

## Task 1: The shared step

**Files:**
- Create: `app/services/openvpn_setup.py`, `app/bot/keyboards/openvpn_setup.py`, `app/bot/handlers/openvpn_setup.py`
- Modify: `app/i18n/texts.py`, `app/main.py`, `app/services/tutorial_delivery.py`
- Test: `tests/functional/test_openvpn_setup.py`

**Interfaces:**
- Produces: `async send_openvpn_setup(bot, telegram_id, session, *, lang) -> None`; `openvpn_platform_keyboard(platforms, lang)`; callback `ovpn:link:<platform_id>`; `send_guide(..., notify_if_missing: bool = True)`.

- [ ] **Step 1: Write the failing tests**

`tests/functional/test_openvpn_setup.py`:

```python
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession


async def _platform_id(label: str) -> int:
    async with async_session_maker() as session:
        return (
            await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == label))
        ).scalar_one().id


async def _seed_links() -> None:
    from app.services.app_config import set_config
    from app.services.tutorial_delivery import download_link_key

    async with async_session_maker() as session:
        for label, url in (
            ("iOS", "https://apps.apple.com/openvpn"),
            ("Android", "https://play.google.com/openvpn"),
            ("Windows", "https://openvpn.net/windows"),
            ("macOS", "https://openvpn.net/macos"),
        ):
            await set_config(session, download_link_key(protocol_label="OpenVPN", platform_label=label), url)


def _texts(fake_session: FakeBotSession) -> str:
    return " ".join((c[1].get("text") or c[1].get("caption") or "") for c in fake_session.calls)


@pytest.mark.asyncio
async def test_setup_step_sends_the_profile_then_a_platform_prompt(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.openvpn_setup import send_openvpn_setup
    from app.services.tutorials import upsert_profile

    async with async_session_maker() as session:
        await upsert_profile(
            session, platform_id=None, name="ir.alonet.ovpn",
            file_id="ovpn-file-id", file_type="document", text=None,
        )
    await _seed_links()

    async with async_session_maker() as session:
        await send_openvpn_setup(bot, 4001, session, lang="en")

    kinds = [c[0] for c in fake_session.calls]
    assert "sendDocument" in kinds, "the .ovpn config still goes out"
    assert kinds.index("sendDocument") < kinds.index("sendMessage"), "config first, then the prompt"

    prompt = [c for c in fake_session.calls if c[0] == "sendMessage"][-1][1]
    labels = {b["text"]: b.get("callback_data") for row in prompt["reply_markup"]["inline_keyboard"] for b in row}
    ios = await _platform_id("iOS")
    assert labels["iOS"] == f"ovpn:link:{ios}"
    assert {"iOS", "Android", "Windows", "macOS"} <= set(labels)


@pytest.mark.asyncio
async def test_no_links_are_sent_until_a_platform_is_picked(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """The whole point of the change: four links in one message is what
    this replaces."""
    from app.services.openvpn_setup import send_openvpn_setup

    await _seed_links()
    async with async_session_maker() as session:
        await send_openvpn_setup(bot, 4002, session, lang="en")

    text = _texts(fake_session)
    for url in ("apps.apple.com", "play.google.com", "openvpn.net/windows", "openvpn.net/macos"):
        assert url not in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "wanted", "others"),
    [
        ("iOS", "https://apps.apple.com/openvpn", ["play.google.com", "openvpn.net/windows", "openvpn.net/macos"]),
        ("Android", "https://play.google.com/openvpn", ["apps.apple.com", "openvpn.net/windows", "openvpn.net/macos"]),
        ("Windows", "https://openvpn.net/windows", ["apps.apple.com", "play.google.com", "openvpn.net/macos"]),
        ("macOS", "https://openvpn.net/macos", ["apps.apple.com", "play.google.com", "openvpn.net/windows"]),
    ],
)
async def test_picking_a_platform_sends_only_that_link(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    label: str, wanted: str, others: list[str],
) -> None:
    await _seed_links()
    platform_id = await _platform_id(label)

    await dispatcher.feed_update(bot, make_callback_update(4003, f"ovpn:link:{platform_id}"))

    text = _texts(fake_session)
    assert wanted in text
    for other in others:
        assert other not in text


@pytest.mark.asyncio
async def test_a_platform_without_a_link_answers_with_an_alert(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    platform_id = await _platform_id("macOS")  # nothing seeded

    await dispatcher.feed_update(bot, make_callback_update(4004, f"ovpn:link:{platform_id}"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True


@pytest.mark.asyncio
async def test_the_setup_step_never_says_a_guide_is_not_ready(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """No OpenVPN guide has ever been uploaded, and this step does not
    look one up - so the placeholder cannot fire here."""
    from app.services.openvpn_setup import send_openvpn_setup

    async with async_session_maker() as session:
        await send_openvpn_setup(bot, 4005, session, lang="en")

    assert "not ready" not in _texts(fake_session).lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_openvpn_setup.py -q`
Expected: FAIL with `ModuleNotFoundError: app.services.openvpn_setup`.

- [ ] **Step 3: Add the two i18n keys**

English:

```python
        "openvpn_pick_platform": (
            "📥 <b>Download OpenVPN Connect</b>\n\n"
            "Pick your device and we'll send you the download link."
        ),
        "openvpn_link_unavailable": "⚠️ No download link is configured for that device yet — please contact support.",
```

Persian:

```python
        "openvpn_pick_platform": (
            "📥 <b>دانلود OpenVPN Connect</b>\n\n"
            "دستگاه خود را انتخاب کنید تا لینک دانلود برایتان ارسال شود."
        ),
        "openvpn_link_unavailable": "⚠️ برای این دستگاه هنوز لینک دانلودی تنظیم نشده — لطفاً با پشتیبانی تماس بگیرید.",
```

- [ ] **Step 4: Add the keyboard**

`app/bot/keyboards/openvpn_setup.py`:

```python
"""The platform picker sent after an account handover.

Platform labels come from the catalog (iOS, Android, ...) and are proper
nouns, so they are not translated; every other string here goes through
t()."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.i18n.texts import t


def openvpn_platform_keyboard(platforms: list[TutorialPlatform], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"ovpn:link:{platform.id}")
    # Anyone wanting the full walkthrough rather than just the app goes
    # to Tutorials, which owns the guides.
    builder.button(text=t("tutorial_button", lang), callback_data="menu:tutorials")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
```

- [ ] **Step 5: Add the service**

`app/services/openvpn_setup.py`:

```python
"""The OpenVPN setup step every account handover ends with.

Sends the .ovpn config, then asks which device the customer is on and
sends only that platform's download link when they answer. It replaced a
single message listing all four links at once.

Deliberately looks up NO guide: none has ever been uploaded for OpenVPN,
and the lookup's honest "not ready" answer had been reaching customers
in the middle of a successful purchase. Guides live in the Tutorials
section, which this step's keyboard links to.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.openvpn_setup import openvpn_platform_keyboard
from app.i18n.texts import t
from app.services.tutorial_delivery import send_profile
from app.services.tutorials import list_platforms

logger = logging.getLogger(__name__)

OPENVPN_LABEL = "OpenVPN"


async def send_openvpn_setup(bot: Bot, telegram_id: int, session: AsyncSession, *, lang: str) -> None:
    """Config file first, then the platform prompt. Never raises: the
    account is already provisioned, so a missing profile or an empty
    platform list must not look like a failed handover."""
    await send_profile(bot, telegram_id, session, platform_id=None, lang=lang)

    platforms = await list_platforms(session)
    if not platforms:
        logger.warning("OpenVPN setup: no active platforms configured, skipping the download prompt")
        return

    await bot.send_message(
        telegram_id, t("openvpn_pick_platform", lang), reply_markup=openvpn_platform_keyboard(platforms, lang)
    )
```

- [ ] **Step 6: Add the router**

`app/bot/handlers/openvpn_setup.py`:

```python
"""The ovpn:* callbacks behind the post-handover platform picker."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.openvpn_setup import OPENVPN_LABEL
from app.services.tutorial_delivery import send_download_links

logger = logging.getLogger(__name__)

router = Router(name="openvpn_setup")


@router.callback_query(F.data.startswith("ovpn:link:"))
async def openvpn_link_cb(callback: CallbackQuery, lang: str) -> None:
    try:
        platform_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    async with async_session_maker() as session:
        platform = await session.get(TutorialPlatform, platform_id)
        protocol = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == OPENVPN_LABEL))
        ).scalar_one_or_none()
        if platform is None or protocol is None:
            await callback.answer()
            return
        sent = await send_download_links(
            callback.bot, callback.from_user.id, session, protocol=protocol, platform=platform, lang=lang
        )

    # The keyboard stays put so a customer with two devices can take both
    # links; only the toast differs.
    if sent:
        await callback.answer()
    else:
        await callback.answer(t("openvpn_link_unavailable", lang), show_alert=True)
```

Register it in `app/main.py` alongside the other customer routers, before `users.router`.

- [ ] **Step 7: Silence the placeholder in delivery flows**

In `app/services/tutorial_delivery.py`, give `send_guide` the new argument:

```python
async def send_guide(
    bot: Bot, telegram_id: int, session: AsyncSession, *, protocol_id: int, platform_id: int | None,
    lang: str, fall_back_to_generic: bool = False, notify_if_missing: bool = True,
) -> int | None:
```

and in its missing branch:

```python
    if guide is None or (guide.media_file_id is None and guide.body_html is None):
        if notify_if_missing:
            await bot.send_message(telegram_id, t("guide_not_ready", lang))
        return None
```

`deliver_setup` passes `notify_if_missing=False`: a delivery flow that
has already handed over working credentials must not apologise for a
guide the customer did not ask for. Tutorials keeps the default.

- [ ] **Step 8: Run**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_openvpn_setup.py tests/functional/test_tutorials_flow.py -q`
Expected: PASS, including the Tutorials test that still expects "not ready".

- [ ] **Step 9: Commit**

```bash
git add app tests
git commit -m "feat: platform-specific OpenVPN download step"
```

---

## Task 2: All four flows call it

**Files:**
- Modify: `app/services/payments/confirmation.py`, `app/bot/handlers/trial.py`, `app/bot/handlers/myservices.py`
- Test: `tests/functional/test_payment_recovery.py`, `test_trial_flow.py`, `test_myservices_flow.py`

- [ ] **Step 1: Write the failing tests**

One per flow, asserting the platform prompt arrives after the credentials and that no link is sent unprompted:

```python
@pytest.mark.asyncio
async def test_purchase_ends_with_the_openvpn_platform_prompt(...) -> None:
    """Paid flows sent no setup material at all before this change."""
    # drive a purchase through the callback as the existing tests do
    prompt = [c for c in fake_session.calls if c[0] == "sendMessage"][-1][1]
    assert "Download OpenVPN Connect" in prompt["text"]
    labels = {b["text"] for row in prompt["reply_markup"]["inline_keyboard"] for b in row}
    assert {"iOS", "Android", "Windows", "macOS"} <= labels
```

Mirror it for renewal, for the trial's OpenVPN branch, and for My Services "Resend Setup". In the trial and My Services tests, replace any assertion that all four links arrive at once.

- [ ] **Step 2: Call it from the paid flows**

In `confirmation.py`, after `send_account_delivery(...)`:

```python
    # Paid flows previously ended at the credentials; the setup step is
    # what makes purchase, renewal and trial behave alike.
    await send_openvpn_setup(bot, payment.telegram_id, session, lang=lang)
```

- [ ] **Step 3: Call it from trial and My Services**

Replace the `deliver_setup(..., platform_id=None)` call in each OpenVPN branch with `send_openvpn_setup(...)`. In the trial that call currently gates the credentials on its `delivered` return; since the new function always succeeds, send the credentials first and then the setup step, which also puts the messages in a more sensible order.

- [ ] **Step 4: Full suite**

Run: `make test`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "refactor: every handover flow ends with the shared OpenVPN setup step"
```

---

## Task 3: Docs and deploy

- [ ] **Step 1: CLAUDE.md**

Record that `app/services/openvpn_setup.py` is the single post-handover setup step, and that delivery flows never emit `guide_not_ready`.

- [ ] **Step 2: Deploy and verify**

```bash
git push origin main
ssh homeland-bot-server 'cd ~/Homeland-Bot && git pull --ff-only && docker compose up -d --build && docker compose logs --tail=10 bot'
```

Run a free trial from a test account: expect the credentials message, the
`.ovpn` file, the four platform buttons, exactly one link per tap, and no
"not ready" message anywhere.

---

## Self-Review

- **Spec coverage:** §2 what it sends → Task 1 Steps 4–6; §3 one function and its callers → Tasks 1–2; §4 placeholder → Task 1 Step 7; §5 copy → Task 1 Step 3; §6 tests → Tasks 1–2.
- **Placeholder scan:** Task 2 Step 1 gives one test in full and names the three mirrors rather than repeating near-identical bodies; every production code path is given in full.
- **Type consistency:** `send_openvpn_setup(bot, telegram_id, session, *, lang)` matches all four call sites and every test; `send_download_links(bot, telegram_id, session, *, protocol, platform, lang) -> bool` matches its existing signature; `send_guide`'s new `notify_if_missing` defaults True so Tutorials is unchanged.
