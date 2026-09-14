"""In-process fake aiogram BaseSession - never makes a real HTTP call to
Telegram. Records every outbound API call (for test assertions) and
returns plausible synthetic responses for every method this codebase
actually calls, with a loud failure for anything uncovered."""

from __future__ import annotations

import datetime as dt
import itertools
from typing import Any

from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, ChatMemberOwner, Message, User


class FakeBotSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._message_id_counter = itertools.count(1)

    def reset(self) -> None:
        self.calls = []

    async def close(self) -> None:
        return None

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        raise NotImplementedError("FakeBotSession.stream_content is not implemented - this app doesn't use it")
        yield b""  # pragma: no cover

    def _fake_message(self, chat_id: int, **extra: Any) -> Message:
        return Message(
            message_id=next(self._message_id_counter),
            date=dt.datetime.now(dt.timezone.utc),
            chat=Chat(id=chat_id, type="private"),
            **extra,
        )

    async def make_request(self, bot, method, timeout: int | None = None):
        api_name = method.__api_method__
        data = method.model_dump(exclude_none=True)
        self.calls.append((api_name, data))

        chat_id = data.get("chat_id", 0)

        if api_name in ("sendMessage", "sendPhoto", "sendDocument", "sendVideo"):
            return self._fake_message(chat_id, text=data.get("text") or data.get("caption") or "")
        if api_name in ("editMessageText", "editMessageCaption", "editMessageReplyMarkup"):
            return self._fake_message(chat_id, text=data.get("text") or data.get("caption") or "")
        if api_name == "deleteMessage":
            return True
        if api_name == "answerCallbackQuery":
            return True
        if api_name == "getChatMember":
            return ChatMemberOwner(status="creator", user=User(id=data.get("user_id", 0), is_bot=False, first_name="Fake"), is_anonymous=False)
        if api_name == "getChat":
            return Chat(id=chat_id, type="private")
        if api_name == "setMyCommands":
            return True
        if api_name == "deleteWebhook":
            return True
        if api_name == "getMe":
            return User(id=999999, is_bot=True, first_name="TestBot", username="test_bot")

        returning = method.__returning__
        if returning is bool:
            return True
        if returning is int:
            return 0
        raise NotImplementedError(
            f"FakeBotSession has no handler for API method {api_name!r} (returning {returning!r}) - "
            "add one in tests/fakes/fake_bot_session.py rather than letting this call hit real Telegram."
        )
