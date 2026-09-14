"""Regression tests for the global aiogram error handler.

The bug these guard against: handle_pool_timeout used to return False for
anything that wasn't a pool timeout. aiogram's ErrorsMiddleware only
re-raises the original exception when the error handler's response
`is UNHANDLED`, and `False is not UNHANDLED` - so every bug in every
handler was marked "handled" and silently discarded with no traceback."""

from __future__ import annotations

from typing import Any

import pytest
from aiogram import Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import ErrorEvent, Message
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.bot.error_handlers import handle_pool_timeout
from tests.factories import make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


def _boom_dispatcher(exception: Exception) -> Any:
    """A throwaway Dispatcher wired exactly like build_dispatcher's error
    handling, whose only handler raises. Built locally rather than on the
    session-scoped `dispatcher` fixture so no permanent throwaway handler
    ever reaches production routers."""
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    router = Router(name="test-explosive-handler")

    @router.message()
    async def _explode(message: Message) -> None:
        raise exception

    dp = Dispatcher(storage=MemoryStorage())
    dp.errors.register(handle_pool_timeout)
    dp.include_router(router)
    return dp


@pytest.mark.asyncio
async def test_handle_pool_timeout_returns_unhandled_for_other_exceptions() -> None:
    event = ErrorEvent(update=make_message_update(4101, "boom"), exception=RuntimeError("kaboom"))
    assert await handle_pool_timeout(event) is UNHANDLED


@pytest.mark.asyncio
async def test_non_pool_exception_propagates_instead_of_being_swallowed(bot: Any) -> None:
    dp = _boom_dispatcher(RuntimeError("handler exploded"))

    with pytest.raises(RuntimeError, match="handler exploded"):
        await dp.feed_update(bot, make_message_update(4102, "boom"))


@pytest.mark.asyncio
async def test_pool_timeout_is_handled_and_warns_the_user(bot: Any, fake_session: FakeBotSession) -> None:
    dp = _boom_dispatcher(PoolTimeoutError("pool exhausted"))

    # No raise: a pool timeout is the one exception this handler claims.
    await dp.feed_update(bot, make_message_update(4103, "boom"))

    sent = [call for call in fake_session.calls if call[0] == "sendMessage"]
    assert len(sent) == 1
    assert "temporarily busy" in sent[0][1]["text"]


@pytest.mark.asyncio
async def test_production_dispatcher_registers_the_error_handler(dispatcher: Any) -> None:
    """The fixture builds the real app.main.build_dispatcher, so this also
    proves main()'s wiring includes the error handler."""
    registered = [handler.callback for handler in dispatcher.errors.handlers]
    assert handle_pool_timeout in registered
