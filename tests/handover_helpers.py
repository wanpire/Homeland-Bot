"""Driving the shared handover sequence (app/services/handover.py) from a test.

Purchase, renewal and trial all end on the same `ho:*` device picker, so
tests for any of them tap through it the same way."""

from __future__ import annotations

from typing import Any

from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession


def _buttons(payload: dict[str, Any]) -> dict[str, str]:
    rows = (payload.get("reply_markup") or {}).get("inline_keyboard") or []
    return {b["text"]: b.get("callback_data") or "" for row in rows for b in row}


def latest_device_picker(fake_session: FakeBotSession, telegram_id: int) -> dict[str, str]:
    """The newest `ho:*:os:` keyboard shown to this chat, sent or edited in."""
    for name, payload in reversed(fake_session.calls):
        if name not in ("sendMessage", "editMessageText") or payload.get("chat_id") not in (telegram_id, None):
            continue
        buttons = _buttons(payload)
        if any(":os:" in cb and cb.startswith("ho:") for cb in buttons.values()):
            return buttons
    raise AssertionError(f"no handover device picker was shown to {telegram_id}")


def pair_attachments(fake_session: FakeBotSession) -> list[dict[str, Any]]:
    """editMessageReplyMarkup calls that put the Tutorial/Back pair on a message."""
    found = []
    for name, payload in fake_session.calls:
        if name != "editMessageReplyMarkup":
            continue
        if set(_buttons(payload).values()) == {"menu:tutorials", "menu:root"}:
            found.append(payload)
    return found


async def tap_through_handover(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, telegram_id: int,
    *, platform: str = "iOS", protocol: str = "OpenVPN",
) -> None:
    """Tap `platform` on the newest device picker, then `protocol` if the
    protocol step is shown (it is skipped when only one protocol fits)."""
    device_cb = latest_device_picker(fake_session, telegram_id)[platform]
    start = len(fake_session.calls)
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, device_cb))

    for name, payload in fake_session.calls[start:]:
        if name == "editMessageText":
            buttons = _buttons(payload)
            if any(":pr:" in cb for cb in buttons.values()):
                await dispatcher.feed_update(bot, make_callback_update(telegram_id, buttons[protocol]))
                return
