# Ad Campaign Broadcast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the admin panel's Broadcast button into a submenu (Announcement = existing flow, Ad Campaign = new) where a campaign is a photo/text message with an optional single inline button, sent through the same recipient list and send loop as announcements.

**Architecture:** The send loop moves out of `app/bot/handlers/broadcast.py` into a new `app/services/broadcast.py` that accepts an optional per-language keyboard factory; both flows call it. The campaign flow is its own router (`app/bot/handlers/campaign.py`) with its own FSM, keyboards and a section table (`CAMPAIGN_SECTIONS`) that reuses the main menu's callback data verbatim. A tiny `show_screen` helper lets the five main-menu section entry handlers work when tapped under a photo message.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, existing pytest functional harness (`make test`, isolated Docker stack).

**Spec:** `docs/superpowers/specs/2026-09-19-ad-campaign-broadcast-design.md`

## Global Constraints

- Admin-facing strings are English-only and never go through `t()`. Customer-facing button labels for reused sections go through `t("menu_<key>", lang)`.
- Router wiring happens only in `app/main.py`'s `build_dispatcher`; the campaign router must be registered before `admin_fallback.router`.
- Every screen has a Back or Cancel button; every Back/Cancel handler clears or rewinds FSM state.
- Send loop semantics are unchanged: 0.05 s between sends, `TelegramAPIError` counted as failed, admin excluded, blocked users excluded, strong-reference task set.
- Custom label: 1–64 chars after strip. URL: starts with `http://`, `https://` or `tg://`, no whitespace, ≤ 1024 chars.
- Tests go through the real dispatcher and assert on `fake_session.calls`.
- Run the suite with `make test` (Docker) — the plain `pytest` command needs the test Postgres/Redis and will not work locally.

---

## File Structure

- **Create** `app/services/broadcast.py` — `list_recipients`, `run_broadcast`, `start_broadcast_task`, `Content`, `KeyboardFor`.
- **Modify** `app/bot/handlers/broadcast.py` — submenu handler on `adm:broadcast`; existing compose moves to `adm:broadcast:announce`; delegates sending to the service.
- **Modify** `app/bot/keyboards/broadcast.py` — add `broadcast_submenu_keyboard()`.
- **Create** `app/bot/states/campaign.py` — `CampaignStates`.
- **Create** `app/bot/keyboards/campaign.py` — `CAMPAIGN_SECTIONS`, `campaign_keyboard`, and the admin screens' keyboards.
- **Create** `app/bot/handlers/campaign.py` — the campaign router.
- **Modify** `app/bot/keyboards/menus.py` — add `show_screen`.
- **Modify** `app/bot/handlers/buy.py`, `renew.py`, `trial.py`, `myservices.py`, `users.py` — entry handlers use `show_screen`.
- **Modify** `app/main.py` — register `campaign.router`.
- **Modify** `tests/functional/test_broadcast.py`, `tests/functional/test_admin_panel_root.py` — new start callback / submenu.
- **Create** `tests/functional/test_campaign.py`.

---

### Task 1: Broadcast service + submenu (announcement flow re-homed)

**Files:**
- Create: `app/services/broadcast.py`
- Modify: `app/bot/handlers/broadcast.py`, `app/bot/keyboards/broadcast.py`
- Test: `tests/functional/test_broadcast.py`, `tests/functional/test_admin_panel_root.py`

**Interfaces:**
- Produces:
  - `Content = dict[str, Any]`
  - `KeyboardFor = Callable[[str], InlineKeyboardMarkup | None]`
  - `async def list_recipients(session: AsyncSession, *, exclude_telegram_id: int) -> list[tuple[int, str]]`
  - `async def run_broadcast(bot: Bot, admin_telegram_id: int, content: Content, *, keyboard_for: KeyboardFor | None = None, summary_label: str = "Broadcast") -> None`
  - `def start_broadcast_task(bot: Bot, admin_telegram_id: int, content: Content, *, keyboard_for: KeyboardFor | None = None, summary_label: str = "Broadcast") -> asyncio.Task[None]`
  - callback `adm:broadcast:announce` starts the announcement compose; `adm:broadcast` shows the submenu.

- [ ] **Step 1: Update existing tests to the new callback and add a submenu test**

In `tests/functional/test_broadcast.py`, replace every `make_callback_update(FAKE_ADMIN_ID, "adm:broadcast")` and `make_callback_update(701, "adm:broadcast")` with `"adm:broadcast:announce"`. Then append:

```python
@pytest.mark.asyncio
async def test_broadcast_submenu_offers_announcement_campaign_and_back(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited, "submenu must render"
    buttons = {b["text"]: b["callback_data"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row}
    assert buttons["📣 Announcement"] == "adm:broadcast:announce"
    assert buttons["🎯 Ad Campaign"] == "adm:broadcast:campaign"
    assert any("back" in text.lower() for text in buttons)
```

`tests/functional/test_admin_panel_root.py::test_unmatched_adm_callback_gets_a_permission_alert_not_silence` feeds `adm:broadcast` as a sales admin and still expects the permission alert — unchanged, it keeps passing because the router filter is `IsFullAdmin`.

- [ ] **Step 2: Run to verify the new test fails**

Run: `make test` (or, with the stack already up, `docker compose -f docker-compose.test.yml -p homeland_bot_test exec -T test-runner python -m pytest tests/functional/test_broadcast.py -v`)
Expected: `test_broadcast_submenu_offers_announcement_campaign_and_back` FAILS; the renamed tests fail too (no `adm:broadcast:announce` handler yet).

- [ ] **Step 3: Create the service**

`app/services/broadcast.py`:

```python
"""The one outbound mass-messaging pipeline, shared by the admin
Announcement flow and the Ad Campaign flow (app/bot/handlers/broadcast.py
and campaign.py). Recipient rules, pacing, failure accounting and the
summary DM all live here so the two flows can never drift apart."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser
from app.db.session import async_session_maker
from app.i18n.texts import DEFAULT_LANG

logger = logging.getLogger(__name__)

Content = dict[str, Any]
KeyboardFor = Callable[[str], InlineKeyboardMarkup | None]

_SEND_DELAY_SECONDS = 0.05

# asyncio.create_task() only leaves the task referenced by the event
# loop's internal *weak* set - with nothing else keeping it alive, the
# task can be garbage-collected mid-run in a long-lived polling process,
# silently truncating a broadcast with no error and no summary DM. This
# set holds a strong reference to every in-flight task; the done-callback
# discards it once the task finishes (success or not), so it doesn't leak.
_background_tasks: set[asyncio.Task[None]] = set()


async def list_recipients(session: AsyncSession, *, exclude_telegram_id: int) -> list[tuple[int, str]]:
    """(telegram_id, lang) for every tracked, unblocked bot user except the
    admin running the send - UserTrackingMiddleware records the admin's
    own interaction too, so without excluding them they'd receive their
    own announcement (and its summary) as if they were a recipient.
    Blocked users (BotUser.is_blocked) are excluded too: BlockedUserMiddleware
    stops them from interacting with the bot, but nothing stops the bot
    from messaging them unless this query does. A user who never picked a
    language gets DEFAULT_LANG, the same fallback app/services/reminders.py
    uses."""
    result = await session.execute(
        select(BotUser.telegram_id, BotUser.language).where(
            BotUser.is_blocked.is_(False),
            BotUser.telegram_id != exclude_telegram_id,
        )
    )
    return [(row[0], row[1] or DEFAULT_LANG) for row in result.all()]


async def run_broadcast(
    bot: Bot,
    admin_telegram_id: int,
    content: Content,
    *,
    keyboard_for: KeyboardFor | None = None,
    summary_label: str = "Broadcast",
) -> None:
    async with async_session_maker() as session:
        recipients = await list_recipients(session, exclude_telegram_id=admin_telegram_id)

    sent, failed = 0, 0
    for telegram_id, lang in recipients:
        reply_markup = keyboard_for(lang) if keyboard_for is not None else None
        try:
            if content["kind"] == "text":
                await bot.send_message(telegram_id, content["text"], reply_markup=reply_markup)
            elif content["kind"] == "photo":
                await bot.send_photo(
                    telegram_id, content["file_id"], caption=content["caption"] or None, reply_markup=reply_markup
                )
            else:
                await bot.send_document(
                    telegram_id, content["file_id"], caption=content["caption"] or None, reply_markup=reply_markup
                )
            sent += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(_SEND_DELAY_SECONDS)

    try:
        await bot.send_message(admin_telegram_id, f"✅ {summary_label} done — sent: {sent}, failed: {failed}.")
    except TelegramAPIError:
        logger.exception("Could not deliver %s summary to admin telegram_id=%s", summary_label.lower(), admin_telegram_id)


def start_broadcast_task(
    bot: Bot,
    admin_telegram_id: int,
    content: Content,
    *,
    keyboard_for: KeyboardFor | None = None,
    summary_label: str = "Broadcast",
) -> asyncio.Task[None]:
    task = asyncio.create_task(
        run_broadcast(bot, admin_telegram_id, content, keyboard_for=keyboard_for, summary_label=summary_label)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
```

- [ ] **Step 4: Add the submenu keyboard**

Append to `app/bot/keyboards/broadcast.py`:

```python
def broadcast_submenu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📣 Announcement", callback_data="adm:broadcast:announce")
    builder.button(text="🎯 Ad Campaign", callback_data="adm:broadcast:campaign")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Rewrite the handler to use the service and expose the submenu**

Replace `app/bot/handlers/broadcast.py` with:

```python
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin import admin_root_menu
from app.bot.keyboards.broadcast import (
    broadcast_compose_keyboard,
    broadcast_confirm_keyboard,
    broadcast_submenu_keyboard,
)
from app.bot.states.broadcast import BroadcastStates
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.broadcast import list_recipients, start_broadcast_task

router = Router(name="broadcast")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

SUBMENU_TEXT = "📢 <b>Broadcast</b>\n\nAnnouncement: plain message to every user.\nAd Campaign: photo/text with an optional button."
_COMPOSE_TEXT = "📢 Send the message to broadcast — text, a photo, or a document:"


@router.callback_query(F.data == "adm:broadcast")
async def broadcast_submenu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(SUBMENU_TEXT, reply_markup=broadcast_submenu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm:broadcast:announce")
async def broadcast_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.content)
    if callback.message is not None:
        await callback.message.edit_text(_COMPOSE_TEXT, reply_markup=broadcast_compose_keyboard())
    await callback.answer()


@router.message(BroadcastStates.content)
async def broadcast_receive_content_msg(message: Message, state: FSMContext) -> None:
    # message.html_text re-renders the message's formatting entities as
    # HTML and correctly escapes any literal &/</> the admin typed - the
    # bot's default parse mode is HTML (app/main.py), and a raw,
    # unescaped message.text/message.caption containing one of those
    # characters makes Telegram reject the whole send as malformed HTML.
    # (When only a caption is set, message.text is None, so html_text
    # falls back to rendering message.caption/caption_entities - aiogram
    # has no separate html_caption property.)
    if message.photo:
        content: dict[str, Any] = {"kind": "photo", "file_id": message.photo[-1].file_id, "caption": message.html_text}
    elif message.document:
        content = {"kind": "document", "file_id": message.document.file_id, "caption": message.html_text}
    elif message.text:
        content = {"kind": "text", "text": message.html_text}
    else:
        await message.answer("⚠️ Send text, a photo, or a document.", reply_markup=broadcast_compose_keyboard())
        return

    await state.update_data(content=content)
    await state.set_state(BroadcastStates.confirm)

    async with async_session_maker() as session:
        recipient_count = len(await list_recipients(session, exclude_telegram_id=message.from_user.id))
    await message.answer(
        f"📢 Ready to broadcast to {recipient_count} user(s). Send it?",
        reply_markup=broadcast_confirm_keyboard(),
    )


@router.callback_query(BroadcastStates.confirm, F.data == "adm:broadcast:confirm")
async def broadcast_confirm_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    content = data["content"]
    await state.clear()

    if callback.message is not None:
        await callback.message.edit_text("📤 Broadcast started — you'll get a summary when it's done.")
    await callback.answer()

    start_broadcast_task(callback.bot, callback.from_user.id, content)


@router.callback_query(F.data == "adm:broadcast:cancel")
async def broadcast_cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        is_sales = await has_level(session, callback.from_user.id, "sales")
        is_full = await has_level(session, callback.from_user.id, "full")
    if callback.message is not None:
        await callback.message.edit_text(
            "🛠 <b>Admin Panel</b>", reply_markup=admin_root_menu(is_sales_admin=is_sales, is_full_admin=is_full)
        )
    await callback.answer()
```

- [ ] **Step 6: Run the broadcast + admin-root tests, verify they pass**

Run: `docker compose -f docker-compose.test.yml -p homeland_bot_test exec -T test-runner python -m pytest tests/functional/test_broadcast.py tests/functional/test_admin_panel_root.py tests/functional/test_reminders.py -v`
Expected: all PASS (`test_reminders.py` is included because its docstring references the old function name only in prose; nothing imports it).

- [ ] **Step 7: Commit**

```bash
git add app/services/broadcast.py app/bot/handlers/broadcast.py app/bot/keyboards/broadcast.py tests/functional/test_broadcast.py
git commit -m "refactor: move broadcast send loop into a service and add the Broadcast submenu"
```

---

### Task 2: `show_screen` helper for photo-message navigation

**Files:**
- Modify: `app/bot/keyboards/menus.py`, `app/bot/handlers/buy.py:41-49`, `app/bot/handlers/renew.py:89-102`, `app/bot/handlers/trial.py:96-108`, `app/bot/handlers/myservices.py:29-43`, `app/bot/handlers/users.py:51-62`
- Test: `tests/functional/test_campaign.py` (created here, extended in Task 4)

**Interfaces:**
- Produces: `async def show_screen(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None) -> None` in `app/bot/keyboards/menus.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/functional/test_campaign.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import (
    FAKE_ADMIN_ID,
    make_callback_update,
    make_message_update,
    make_photo_message,
    make_photo_message_update,
    seed_bot_user,
)
from tests.fakes.fake_bot_session import FakeBotSession


async def _drain_background_tasks() -> None:
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks)


def _buttons(markup: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [b for row in (markup or {"inline_keyboard": []})["inline_keyboard"] for b in row]


def _last_screen(fake_session: FakeBotSession) -> tuple[str, dict[str, Any]]:
    screens = [c for c in fake_session.calls if c[0] in ("sendMessage", "editMessageText", "sendPhoto")]
    return screens[-1]


@pytest.mark.asyncio
async def test_menu_button_under_a_photo_sends_a_fresh_screen(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A campaign photo's button carries plain main-menu callback data.
    Telegram refuses editMessageText on a photo, so the section entry
    handler must send a new message instead of editing."""
    async with async_session_maker() as session:
        await seed_bot_user(session, 801, username="viewer")

    photo = make_photo_message(801, file_id="campaign-photo")
    await dispatcher.feed_update(bot, make_callback_update(801, "menu:buy", anchor_message=photo))

    assert [c for c in fake_session.calls if c[0] == "editMessageText"] == []
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert sent and sent[-1][1]["chat_id"] == 801
    assert _buttons(sent[-1][1].get("reply_markup")), "buy category screen must carry its keyboard"


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["menu:renew", "menu:trial", "menu:myservices", "menu:support"])
async def test_every_campaign_section_works_under_a_photo(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    async with async_session_maker() as session:
        await seed_bot_user(session, 802, username="viewer2")

    photo = make_photo_message(802, file_id="campaign-photo")
    await dispatcher.feed_update(bot, make_callback_update(802, data, anchor_message=photo))

    assert [c for c in fake_session.calls if c[0] == "editMessageText"] == []
    assert any(c[0] == "sendMessage" and c[1]["chat_id"] == 802 for c in fake_session.calls)
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose -f docker-compose.test.yml -p homeland_bot_test exec -T test-runner python -m pytest tests/functional/test_campaign.py -v`
Expected: FAIL — `editMessageText` is called (the fake session accepts it, so the assertion on the empty list is what fails).

- [ ] **Step 3: Add the helper**

Append to `app/bot/keyboards/menus.py` (add `from aiogram.types import InlineKeyboardMarkup, Message` to the import):

```python
async def show_screen(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None) -> None:
    """Render a menu screen on the message the user tapped. A text
    message is edited in place (the usual case); a message with no text -
    an Ad Campaign photo whose button reuses main-menu callback data -
    can't be edited into a text screen (Telegram: "there is no text in
    the message to edit"), so a fresh message is sent instead. Every
    deeper screen in the flow then runs on that fresh text message and
    can keep using edit_text."""
    if message.text is None:
        await message.answer(text, reply_markup=reply_markup)
    else:
        await message.edit_text(text, reply_markup=reply_markup)
```

- [ ] **Step 4: Switch the five entry handlers**

In each file import `show_screen` from `app.bot.keyboards.menus` and replace only the entry handler's `await callback.message.edit_text(X, reply_markup=Y)` calls with `await show_screen(callback.message, X, Y)`:

- `buy.py` `buy_start_cb` (one call)
- `renew.py` `renew_start_cb` (two calls: empty and list)
- `trial.py` `trial_entry_cb` (two calls: already-used and confirm prompt)
- `myservices.py` `myservices_list_cb` (two calls)
- `users.py` `menu_support_cb` (one call)

Example for `buy_start_cb`:

```python
    if callback.message is not None:
        await show_screen(
            callback.message, t("buy_category_heading", lang), buy_category_keyboard(lang, active_categories)
        )
```

- [ ] **Step 5: Run the new tests plus the touched flows' suites**

Run: `docker compose -f docker-compose.test.yml -p homeland_bot_test exec -T test-runner python -m pytest tests/functional/test_campaign.py tests/functional/test_buy_flow.py tests/functional/test_renew_flow.py tests/functional/test_trial_flow.py tests/functional/test_myservices_flow.py tests/functional/test_start_and_menu.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/bot/keyboards/menus.py app/bot/handlers/buy.py app/bot/handlers/renew.py app/bot/handlers/trial.py app/bot/handlers/myservices.py app/bot/handlers/users.py tests/functional/test_campaign.py
git commit -m "feat: main-menu section entries render a fresh screen when tapped under a photo"
```

---

### Task 3: Campaign states, keyboards and section table

**Files:**
- Create: `app/bot/states/campaign.py`, `app/bot/keyboards/campaign.py`
- Test: `tests/unit/test_campaign_keyboard.py`

**Interfaces:**
- Produces:
  - `CampaignStates` with `content`, `button_choice`, `custom_label`, `custom_dest`, `custom_url`, `confirm`.
  - `CAMPAIGN_SECTIONS: tuple[str, ...] = ("buy", "renew", "trial", "myservices", "support")`
  - `Button = dict[str, Any] | None`
  - `def campaign_keyboard(button: Button, lang: str) -> InlineKeyboardMarkup | None`
  - `def campaign_content_keyboard()`, `campaign_button_choice_keyboard()`, `campaign_section_keyboard(prefix: str)`, `campaign_custom_label_keyboard()`, `campaign_custom_dest_keyboard()`, `campaign_custom_url_keyboard()`, `campaign_confirm_keyboard()` — all `-> InlineKeyboardMarkup`.
  - Callback constants: `CANCEL_CB = "adm:broadcast:cancel"`, `BACK_TO_BUTTON_CB = "adm:broadcast:campaign:btn"`, `CONFIRM_CB = "adm:broadcast:campaign:confirm"`.

- [ ] **Step 1: Write the failing unit test**

`tests/unit/test_campaign_keyboard.py`:

```python
from __future__ import annotations

from app.bot.keyboards.campaign import CAMPAIGN_SECTIONS, campaign_keyboard


def _only_button(markup):  # type: ignore[no-untyped-def]
    rows = markup.inline_keyboard
    assert len(rows) == 1 and len(rows[0]) == 1
    return rows[0][0]


def test_no_button_returns_none() -> None:
    assert campaign_keyboard(None, "fa") is None


def test_menu_button_uses_main_menu_label_and_callback_per_language() -> None:
    fa = _only_button(campaign_keyboard({"kind": "menu", "key": "buy"}, "fa"))
    en = _only_button(campaign_keyboard({"kind": "menu", "key": "buy"}, "en"))
    assert fa.callback_data == en.callback_data == "menu:buy"
    assert fa.text == "🔑 خرید اشتراک"
    assert en.text == "🔑 Buy Subscription"


def test_custom_button_with_section_destination() -> None:
    btn = _only_button(campaign_keyboard({"kind": "custom", "label": "Go!", "dest": {"kind": "menu", "key": "renew"}}, "fa"))
    assert btn.text == "Go!" and btn.callback_data == "menu:renew" and btn.url is None


def test_custom_button_with_url_destination() -> None:
    btn = _only_button(campaign_keyboard({"kind": "custom", "label": "Site", "dest": {"kind": "url", "url": "https://x.y"}}, "en"))
    assert btn.text == "Site" and btn.url == "https://x.y" and btn.callback_data is None


def test_sections_exclude_language_and_tutorials() -> None:
    assert "language" not in CAMPAIGN_SECTIONS and "tutorials" not in CAMPAIGN_SECTIONS
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose -f docker-compose.test.yml -p homeland_bot_test exec -T test-runner python -m pytest tests/unit/test_campaign_keyboard.py -v`
Expected: FAIL with `ModuleNotFoundError: app.bot.keyboards.campaign`.

- [ ] **Step 3: Create the states**

`app/bot/states/campaign.py`:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CampaignStates(StatesGroup):
    content = State()
    button_choice = State()
    custom_label = State()
    custom_dest = State()
    custom_url = State()
    confirm = State()
```

- [ ] **Step 4: Create the keyboards**

`app/bot/keyboards/campaign.py`:

```python
"""Keyboards for the admin Ad Campaign flow (admin screens, English-only)
and the one customer-facing piece: the single button rendered under each
delivered campaign message (campaign_keyboard, bilingual via t())."""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t

# Main-menu sections a campaign button may point at. Each key maps to the
# main menu's own callback data ("menu:<key>") and label ("menu_<key>"),
# so tapping a campaign button lands exactly where the main menu's button
# does. Tutorials (still a coming-soon placeholder) and Language are
# deliberately absent.
CAMPAIGN_SECTIONS: tuple[str, ...] = ("buy", "renew", "trial", "myservices", "support")

# Admin-facing section names for the chooser screens.
SECTION_ADMIN_LABELS: dict[str, str] = {
    "buy": "🔑 Buy Subscription",
    "renew": "♻️ Renew Service",
    "trial": "🎁 Free Trial",
    "myservices": "🛍 My Services",
    "support": "☎️ Support",
}

Button = dict[str, Any] | None

CANCEL_CB = "adm:broadcast:cancel"
BACK_TO_BUTTON_CB = "adm:broadcast:campaign:btn"
CONFIRM_CB = "adm:broadcast:campaign:confirm"


def campaign_keyboard(button: Button, lang: str) -> InlineKeyboardMarkup | None:
    """The keyboard delivered to one recipient. None when the campaign has
    no button. A "menu" button renders the main menu's own label in the
    recipient's language; a "custom" button uses the admin's label
    verbatim for everyone."""
    if button is None:
        return None
    builder = InlineKeyboardBuilder()
    if button["kind"] == "menu":
        key = button["key"]
        builder.button(text=t(f"menu_{key}", lang), callback_data=f"menu:{key}")
    else:
        dest = button["dest"]
        if dest["kind"] == "url":
            builder.button(text=button["label"], url=dest["url"])
        else:
            builder.button(text=button["label"], callback_data=f"menu:{dest['key']}")
    builder.adjust(1)
    return builder.as_markup()


def _cancel_row(builder: InlineKeyboardBuilder) -> None:
    builder.button(text="❌ Cancel", callback_data=CANCEL_CB)


def campaign_content_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data="adm:broadcast")
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_button_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Buy Subscription (preset)", callback_data="adm:broadcast:campaign:btn:preset")
    builder.button(text="📋 Other main-menu button", callback_data="adm:broadcast:campaign:btn:menu")
    builder.button(text="✏️ Custom button", callback_data="adm:broadcast:campaign:btn:custom")
    builder.button(text="➡️ No button", callback_data="adm:broadcast:campaign:btn:none")
    builder.button(text="⬅️ Back", callback_data="adm:broadcast:campaign")
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_section_keyboard(prefix: str, *, exclude: tuple[str, ...] = ()) -> InlineKeyboardMarkup:
    """One row per section, callback f"{prefix}:{key}". Used both for
    "other main-menu button" (prefix adm:broadcast:campaign:btn:menu,
    excluding buy since that is the preset) and for the custom button's
    destination chooser (prefix adm:broadcast:campaign:dest, no exclusions)."""
    builder = InlineKeyboardBuilder()
    for key in CAMPAIGN_SECTIONS:
        if key in exclude:
            continue
        builder.button(text=SECTION_ADMIN_LABELS[key], callback_data=f"{prefix}:{key}")
    builder.button(text="⬅️ Back", callback_data=BACK_TO_BUTTON_CB)
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_custom_dest_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key in CAMPAIGN_SECTIONS:
        builder.button(text=SECTION_ADMIN_LABELS[key], callback_data=f"adm:broadcast:campaign:dest:{key}")
    builder.button(text="🔗 URL", callback_data="adm:broadcast:campaign:dest:url")
    builder.button(text="⬅️ Back", callback_data="adm:broadcast:campaign:btn:custom")
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_back_cancel_keyboard(back_cb: str) -> InlineKeyboardMarkup:
    """For the two text-input steps (custom label, URL)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data=back_cb)
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Send", callback_data=CONFIRM_CB, style="success")
    builder.button(text="⬅️ Back", callback_data=BACK_TO_BUTTON_CB)
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Run the unit test, verify it passes**

Run: `docker compose -f docker-compose.test.yml -p homeland_bot_test exec -T test-runner python -m pytest tests/unit/test_campaign_keyboard.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/bot/states/campaign.py app/bot/keyboards/campaign.py tests/unit/test_campaign_keyboard.py
git commit -m "feat: campaign FSM states, section table and keyboards"
```

---

### Task 4: Campaign router (compose → button → preview → send)

**Files:**
- Create: `app/bot/handlers/campaign.py`
- Modify: `app/main.py` (import + `dp.include_router(campaign.router)` right after `broadcast.router`, before `admin_fallback.router`; extend the comment list)
- Test: `tests/functional/test_campaign.py`

**Interfaces:**
- Consumes: everything from Tasks 1 and 3.

- [ ] **Step 1: Write the failing functional tests**

Append to `tests/functional/test_campaign.py`:

```python
async def _seed_recipients() -> None:
    from app.services.bot_users import set_language

    async with async_session_maker() as session:
        await seed_bot_user(session, 811, username="fa_user")
        await seed_bot_user(session, 812, username="en_user")
        await set_language(session, 811, "fa")
        await set_language(session, 812, "en")


async def _compose_text(dispatcher: Any, bot: Any, text: str = "Big sale!") -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, text))


async def _send(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> list[tuple[str, dict[str, Any]]]:
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:confirm"))
    await _drain_background_tasks()
    return [c for c in fake_session.calls if c[0] in ("sendMessage", "sendPhoto") and c[1]["chat_id"] in (811, 812)]


@pytest.mark.asyncio
async def test_non_full_admin_cannot_start_campaign(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=703, level="sales"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(703, "adm:broadcast:campaign"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("campaign" in c[1].get("text", "").lower() for c in edited)
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[0][1].get("show_alert") is True


@pytest.mark.asyncio
async def test_document_content_is_rejected(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from aiogram.types import Document

    from tests.factories import make_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign"))
    fake_session.reset()
    doc_msg = make_message(FAKE_ADMIN_ID).model_copy(
        update={"document": Document(file_id="doc-1", file_unique_id="doc-1-u")}
    )
    from aiogram.types import Update

    await dispatcher.feed_update(bot, Update(update_id=999001, message=doc_msg))

    text, payload = _last_screen(fake_session)
    assert "photo or text" in payload["text"].lower()
    assert any("cancel" in b["text"].lower() for b in _buttons(payload.get("reply_markup")))


@pytest.mark.asyncio
async def test_preset_buy_button_is_localised_per_recipient(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_recipients()
    await _compose_text(dispatcher, bot)
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:preset"))

    # Preview goes to the admin before the confirm prompt.
    admin_msgs = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == FAKE_ADMIN_ID]
    assert admin_msgs[0][1]["text"] == "Big sale!"
    assert _buttons(admin_msgs[0][1]["reply_markup"])[0]["callback_data"] == "menu:buy"
    assert "2 user" in admin_msgs[-1][1]["text"]

    delivered = await _send(dispatcher, bot, fake_session)
    by_chat = {c[1]["chat_id"]: _buttons(c[1]["reply_markup"])[0] for c in delivered}
    assert by_chat[811]["text"] == "🔑 خرید اشتراک" and by_chat[811]["callback_data"] == "menu:buy"
    assert by_chat[812]["text"] == "🔑 Buy Subscription" and by_chat[812]["callback_data"] == "menu:buy"
    summary = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == FAKE_ADMIN_ID]
    assert "campaign done" in summary[-1][1]["text"].lower() and "sent: 2" in summary[-1][1]["text"]


@pytest.mark.asyncio
async def test_other_menu_button_reuses_section_callback(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_recipients()
    await _compose_text(dispatcher, bot)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:menu"))
    _, chooser = _last_screen(fake_session)
    keys = {b["callback_data"] for b in _buttons(chooser["reply_markup"])}
    assert "adm:broadcast:campaign:btn:menu:renew" in keys
    assert "adm:broadcast:campaign:btn:menu:buy" not in keys  # buy is the preset

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:menu:renew"))
    delivered = await _send(dispatcher, bot, fake_session)
    by_chat = {c[1]["chat_id"]: _buttons(c[1]["reply_markup"])[0] for c in delivered}
    assert by_chat[811] == {"text": "♻️ تمدید سرویس", "callback_data": "menu:renew"}
    assert by_chat[812] == {"text": "♻️ Renew Service", "callback_data": "menu:renew"}


@pytest.mark.asyncio
async def test_custom_button_with_section_destination(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_recipients()
    await _compose_text(dispatcher, bot)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:custom"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "  Try it free  "))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:dest:trial"))

    delivered = await _send(dispatcher, bot, fake_session)
    for c in delivered:
        assert _buttons(c[1]["reply_markup"])[0] == {"text": "Try it free", "callback_data": "menu:trial"}


@pytest.mark.asyncio
async def test_custom_button_with_url_destination(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_recipients()
    await _compose_text(dispatcher, bot)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:custom"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "Our site"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:dest:url"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "https://homeland.example/promo"))

    delivered = await _send(dispatcher, bot, fake_session)
    for c in delivered:
        btn = _buttons(c[1]["reply_markup"])[0]
        assert btn["text"] == "Our site" and btn["url"] == "https://homeland.example/promo"
        assert "callback_data" not in btn


@pytest.mark.asyncio
async def test_invalid_label_and_url_reprompt(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _compose_text(dispatcher, bot)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:custom"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "x" * 65))
    assert "1–64" in _last_screen(fake_session)[1]["text"]

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ok label"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:dest:url"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ftp://nope"))
    assert "valid" in _last_screen(fake_session)[1]["text"].lower()
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "https://ok.example"))
    assert "preview" in _last_screen(fake_session)[1]["text"].lower()


@pytest.mark.asyncio
async def test_no_button_photo_campaign(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_recipients()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign"))
    await dispatcher.feed_update(bot, make_photo_message_update(FAKE_ADMIN_ID, file_id="promo-photo"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:none"))

    delivered = await _send(dispatcher, bot, fake_session)
    assert {c[0] for c in delivered} == {"sendPhoto"}
    assert all(c[1]["photo"] == "promo-photo" and "reply_markup" not in c[1] for c in delivered)


@pytest.mark.asyncio
async def test_every_campaign_screen_offers_back_or_cancel(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    for update in (
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign"),
        make_message_update(FAKE_ADMIN_ID, "Promo"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:menu"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:custom"),
        make_message_update(FAKE_ADMIN_ID, "Label"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:dest:url"),
        make_message_update(FAKE_ADMIN_ID, "https://ok.example"),
    ):
        fake_session.reset()
        await dispatcher.feed_update(bot, update)
        labels = [b["text"].lower() for b in _buttons(_last_screen(fake_session)[1].get("reply_markup"))]
        assert any("back" in l or "cancel" in l for l in labels), update
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose -f docker-compose.test.yml -p homeland_bot_test exec -T test-runner python -m pytest tests/functional/test_campaign.py -v`
Expected: the new tests FAIL (no handler answers `adm:broadcast:campaign`; the admin fallback alerts instead).

- [ ] **Step 3: Create the router**

`app/bot/handlers/campaign.py`:

```python
"""Admin Ad Campaign flow: photo/text + optional single button, delivered
through app/services/broadcast.py exactly like an announcement. Admin
copy is English-only; only the delivered button label is localised."""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.campaign import (
    BACK_TO_BUTTON_CB,
    CAMPAIGN_SECTIONS,
    CONFIRM_CB,
    Button,
    campaign_back_cancel_keyboard,
    campaign_button_choice_keyboard,
    campaign_confirm_keyboard,
    campaign_content_keyboard,
    campaign_custom_dest_keyboard,
    campaign_keyboard,
    campaign_section_keyboard,
)
from app.bot.states.campaign import CampaignStates
from app.db.session import async_session_maker
from app.services.broadcast import list_recipients, start_broadcast_task

router = Router(name="campaign")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

_CONTENT_TEXT = "🎯 <b>Ad Campaign</b>\n\nSend the campaign content — a photo (with optional caption) or text:"
_CONTENT_REJECT_TEXT = "⚠️ Send a photo or text."
_BUTTON_TEXT = "🎯 Add a button under the message?"
_SECTION_TEXT = "📋 Which main-menu button?"
_LABEL_TEXT = "✏️ Send the button label (1–64 characters):"
_LABEL_REJECT_TEXT = "⚠️ Label must be 1–64 characters."
_DEST_TEXT = "✏️ Where should the button go?"
_URL_TEXT = "🔗 Send the URL (http://, https:// or tg://):"
_URL_REJECT_TEXT = "⚠️ Send a valid http(s):// or tg:// URL."
_STARTED_TEXT = "📤 Campaign started — you'll get a summary when it's done."

_LABEL_MAX = 64
_URL_MAX = 1024
_URL_SCHEMES = ("http://", "https://", "tg://")


def _valid_url(value: str) -> bool:
    return value.startswith(_URL_SCHEMES) and len(value) <= _URL_MAX and not any(ch.isspace() for ch in value)


@router.callback_query(F.data == "adm:broadcast:campaign")
async def campaign_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CampaignStates.content)
    if callback.message is not None:
        await callback.message.edit_text(_CONTENT_TEXT, reply_markup=campaign_content_keyboard())
    await callback.answer()


@router.message(CampaignStates.content)
async def campaign_content_msg(message: Message, state: FSMContext) -> None:
    # html_text keeps the admin's formatting and escapes literal &/</> -
    # see app/bot/handlers/broadcast.py for the full reasoning.
    if message.photo:
        content: dict[str, Any] = {"kind": "photo", "file_id": message.photo[-1].file_id, "caption": message.html_text}
    elif message.text:
        content = {"kind": "text", "text": message.html_text}
    else:
        await message.answer(_CONTENT_REJECT_TEXT, reply_markup=campaign_content_keyboard())
        return
    await state.update_data(content=content, button=None)
    await state.set_state(CampaignStates.button_choice)
    await message.answer(_BUTTON_TEXT, reply_markup=campaign_button_choice_keyboard())


@router.callback_query(F.data == BACK_TO_BUTTON_CB)
async def campaign_button_choice_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "content" not in data:
        # Stale keyboard from a finished/cancelled campaign - restart.
        await campaign_start_cb(callback, state)
        return
    await state.set_state(CampaignStates.button_choice)
    if callback.message is not None:
        await callback.message.edit_text(_BUTTON_TEXT, reply_markup=campaign_button_choice_keyboard())
    await callback.answer()


@router.callback_query(CampaignStates.button_choice, F.data == "adm:broadcast:campaign:btn:preset")
async def campaign_preset_cb(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await _go_to_preview(callback, state, lang, {"kind": "menu", "key": "buy"})


@router.callback_query(CampaignStates.button_choice, F.data == "adm:broadcast:campaign:btn:none")
async def campaign_none_cb(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await _go_to_preview(callback, state, lang, None)


@router.callback_query(CampaignStates.button_choice, F.data == "adm:broadcast:campaign:btn:menu")
async def campaign_menu_list_cb(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(
            _SECTION_TEXT, reply_markup=campaign_section_keyboard("adm:broadcast:campaign:btn:menu", exclude=("buy",))
        )
    await callback.answer()


@router.callback_query(CampaignStates.button_choice, F.data.startswith("adm:broadcast:campaign:btn:menu:"))
async def campaign_menu_pick_cb(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    key = callback.data.split(":")[-1]
    if key not in CAMPAIGN_SECTIONS:
        await callback.answer()
        return
    await _go_to_preview(callback, state, lang, {"kind": "menu", "key": key})


@router.callback_query(F.data == "adm:broadcast:campaign:btn:custom")
async def campaign_custom_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if "content" not in await state.get_data():
        await campaign_start_cb(callback, state)
        return
    await state.set_state(CampaignStates.custom_label)
    if callback.message is not None:
        await callback.message.edit_text(_LABEL_TEXT, reply_markup=campaign_back_cancel_keyboard(BACK_TO_BUTTON_CB))
    await callback.answer()


@router.message(CampaignStates.custom_label)
async def campaign_label_msg(message: Message, state: FSMContext) -> None:
    label = (message.text or "").strip()
    if not 1 <= len(label) <= _LABEL_MAX:
        await message.answer(_LABEL_REJECT_TEXT, reply_markup=campaign_back_cancel_keyboard(BACK_TO_BUTTON_CB))
        return
    await state.update_data(custom_label=label)
    await state.set_state(CampaignStates.custom_dest)
    await message.answer(_DEST_TEXT, reply_markup=campaign_custom_dest_keyboard())


@router.callback_query(CampaignStates.custom_dest, F.data == "adm:broadcast:campaign:dest:url")
async def campaign_dest_url_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CampaignStates.custom_url)
    if callback.message is not None:
        await callback.message.edit_text(
            _URL_TEXT, reply_markup=campaign_back_cancel_keyboard("adm:broadcast:campaign:btn:custom")
        )
    await callback.answer()


@router.callback_query(CampaignStates.custom_dest, F.data.startswith("adm:broadcast:campaign:dest:"))
async def campaign_dest_section_cb(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    key = callback.data.split(":")[-1]
    if key not in CAMPAIGN_SECTIONS:
        await callback.answer()
        return
    data = await state.get_data()
    button: Button = {"kind": "custom", "label": data["custom_label"], "dest": {"kind": "menu", "key": key}}
    await _go_to_preview(callback, state, lang, button)


@router.message(CampaignStates.custom_url)
async def campaign_url_msg(message: Message, state: FSMContext, lang: str) -> None:
    url = (message.text or "").strip()
    if not _valid_url(url):
        await message.answer(_URL_REJECT_TEXT, reply_markup=campaign_back_cancel_keyboard("adm:broadcast:campaign:btn:custom"))
        return
    data = await state.get_data()
    button: Button = {"kind": "custom", "label": data["custom_label"], "dest": {"kind": "url", "url": url}}
    await _send_preview(message, state, lang, button)


async def _go_to_preview(callback: CallbackQuery, state: FSMContext, lang: str, button: Button) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _send_preview(callback.message, state, lang, button)


async def _send_preview(target: Message, state: FSMContext, lang: str, button: Button) -> None:
    """Send the admin the real campaign message with the real keyboard (so
    the button can be tapped and verified), then the Send/Back/Cancel
    prompt. `target` is any message in the admin's chat (bot's own or
    the admin's) - only its chat is used."""
    data = await state.get_data()
    content = data["content"]
    await state.update_data(button=button)
    await state.set_state(CampaignStates.confirm)

    markup = campaign_keyboard(button, lang)
    if content["kind"] == "photo":
        await target.answer_photo(content["file_id"], caption=content["caption"] or None, reply_markup=markup)
    else:
        await target.answer(content["text"], reply_markup=markup)

    async with async_session_maker() as session:
        recipient_count = len(await list_recipients(session, exclude_telegram_id=target.chat.id))
    await target.answer(
        f"🎯 Campaign preview above. Send it to {recipient_count} user(s)?", reply_markup=campaign_confirm_keyboard()
    )


@router.callback_query(CampaignStates.confirm, F.data == CONFIRM_CB)
async def campaign_confirm_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    content, button = data["content"], data.get("button")
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_STARTED_TEXT)
    await callback.answer()
    start_broadcast_task(
        callback.bot,
        callback.from_user.id,
        content,
        keyboard_for=lambda lang: campaign_keyboard(button, lang),
        summary_label="Campaign",
    )
```

Note on `exclude_telegram_id=target.chat.id`: in a private chat the chat id equals the admin's telegram id, for both the bot's own message and the admin's message, so the count matches what `run_broadcast` will exclude.

- [ ] **Step 4: Register the router**

In `app/main.py`: add `campaign` to the handlers import list and insert `dp.include_router(campaign.router)` immediately after `dp.include_router(broadcast.router)`, and add `campaign` to the comment's list of adm:* routers.

- [ ] **Step 5: Run the whole suite**

Run: `make test`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/bot/handlers/campaign.py app/main.py tests/functional/test_campaign.py
git commit -m "feat: Ad Campaign broadcast with optional preset/menu/custom button"
```

---

### Task 5: Docs, deploy, live verification

**Files:**
- Modify: `CLAUDE.md` (Architecture: one bullet for `app/services/broadcast.py` and the campaign router), `.claude/skills/aiogram-menu-flow-conventions/SKILL.md` (namespace table: `adm:broadcast:campaign:*`; mention `show_screen` for entry handlers).

- [ ] **Step 1: Update docs and commit**

```bash
git add CLAUDE.md .claude/skills/aiogram-menu-flow-conventions/SKILL.md
git commit -m "docs: note the shared broadcast service, campaign router and show_screen"
```

- [ ] **Step 2: Push and deploy**

```bash
git push origin main
ssh homeland-bot-server 'cd ~/Homeland-Bot && git pull --ff-only && docker compose up -d --build && docker compose logs --tail=30 bot'
```

Expected: bot container restarts cleanly, "Starting polling..." in the log.

- [ ] **Step 3: Live verification (admin account on the real bot)**

Send one campaign per mode to the current bot users and tap the button in each: preset Buy (photo), other section Renew (text), custom label → My Services (photo), custom label → URL (text), no button (photo). Confirm the summary DM arrives with the right counts and that tapping a button under a photo produces a fresh screen rather than an error.

---

## Self-Review

- **Spec coverage:** §1 submenu → Task 1; §2 service → Task 1; §3 callback map → Tasks 3–4 (every entry in the table has a handler in Task 4 or a keyboard in Task 3); §4 FSM + validation → Tasks 3–4; §5 preview/confirm → Task 4 `_send_preview`; §6 `show_screen` → Task 2; §7 tests → Tasks 1–4; §8 rollout → Task 5.
- **Placeholder scan:** none.
- **Type consistency:** `list_recipients` returns `list[tuple[int, str]]` and is used that way in both handlers; `campaign_keyboard(button, lang)` signature matches its use in the lambda and preview; `BACK_TO_BUTTON_CB`/`CONFIRM_CB` names match between keyboard and handler modules.
