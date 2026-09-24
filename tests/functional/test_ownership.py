"""Change Ownership: an offer that moves the account only when the
recipient accepts. See docs/superpowers/specs/2026-09-25-change-ownership-design.md."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update, make_message_update, seed_bot_user
from tests.fakes.fake_bot_session import FakeBotSession

OWNER, RECIPIENT, STRANGER = 7001, 7002, 7003


async def _setup(seeded_catalog: dict, *, owner: int = OWNER, recipient: int = RECIPIENT):  # type: ignore[no-untyped-def]
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    plan = next(p for p in seeded_catalog["plans"] if p["category"] == "scroll" and p["name"] == "1 Month")
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session:
        await seed_bot_user(session, owner, username="owner_user")
        await seed_bot_user(session, recipient, username="New_Owner")
        await seed_bot_user(session, STRANGER, username="stranger")
    async with async_session_maker() as session, IBSngClient() as client:
        return await create_vpn_user(
            session, client, telegram_id=owner, username=username, password=password,
            group_name=plan["group_name"], data_cap_mb=plan["data_cap_mb"], plan_id=plan["id"],
        )


async def _owner_of(vpn_user_id: int) -> int:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        return (await session.get(VPNUser, vpn_user_id)).telegram_id


def _texts_to(fake_session: FakeBotSession, chat_id: int) -> list[str]:
    return [
        c[1].get("text") or "" for c in fake_session.calls
        if c[0] in ("sendMessage", "editMessageText") and c[1].get("chat_id") == chat_id
    ]


def _buttons_in(payload: dict[str, Any]) -> dict[str, str]:
    return {b["text"]: b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row}


def _last_sent(fake_session: FakeBotSession, chat_id: int) -> dict[str, Any]:
    return [c for c in fake_session.calls if c[0] == "sendMessage" and c[1].get("chat_id") == chat_id][-1][1]


async def _cb(dispatcher: Any, bot: Any, telegram_id: int, data: str) -> None:
    usernames = {OWNER: "owner_user", RECIPIENT: "New_Owner", STRANGER: "stranger"}
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, data, username=usernames.get(telegram_id)))


async def _msg(dispatcher: Any, bot: Any, telegram_id: int, text: str) -> None:
    await dispatcher.feed_update(bot, make_message_update(telegram_id, text, username="owner_user"))


async def _offer(dispatcher: Any, bot: Any, fake_session: FakeBotSession, vpn_user_id: int, recipient: str = "@new_owner") -> int:
    """Owner: Change ownership → recipient → Send request. Returns the transfer id."""
    await _cb(dispatcher, bot, OWNER, f"myservices:xfer:{vpn_user_id}")
    await _msg(dispatcher, bot, OWNER, recipient)
    await _cb(dispatcher, bot, OWNER, _buttons_in(_last_sent(fake_session, OWNER))["✅ Send request"])
    offer = _last_sent(fake_session, RECIPIENT)
    accept = next(cb for cb in _buttons_in(offer).values() if cb.startswith("xfer:accept:"))
    return int(accept.split(":")[-1])


# --- Recipient resolution -----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", ["@new_owner", "NEW_OWNER", str(RECIPIENT)])
async def test_the_recipient_resolves_by_username_or_id_and_nothing_moves_yet(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, typed: str
) -> None:
    service = await _setup(seeded_catalog)
    await _cb(dispatcher, bot, OWNER, f"myservices:xfer:{service.id}")
    await _msg(dispatcher, bot, OWNER, typed)

    confirm = _last_sent(fake_session, OWNER)
    assert "@New_Owner" in confirm["text"] and "stays yours until they accept" in confirm["text"]
    assert _buttons_in(confirm)["✅ Send request"] == f"myservices:xferask:{service.id}:{RECIPIENT}"
    assert _texts_to(fake_session, RECIPIENT) == [], "the confirm step sends the recipient nothing"
    assert await _owner_of(service.id) == OWNER


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("typed", "expected"),
    [("@nobody_here", "No bot user found"), ("@owner_user", "That's you"), (str(OWNER), "That's you")],
)
async def test_unusable_recipients_are_refused_and_asked_again(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, typed: str, expected: str
) -> None:
    service = await _setup(seeded_catalog)
    await _cb(dispatcher, bot, OWNER, f"myservices:xfer:{service.id}")
    await _msg(dispatcher, bot, OWNER, typed)
    assert expected in _last_sent(fake_session, OWNER)["text"]

    # Still in the prompt: a valid answer now works.
    await _msg(dispatcher, bot, OWNER, "@new_owner")
    assert "✅ Send request" in _buttons_in(_last_sent(fake_session, OWNER))


@pytest.mark.asyncio
async def test_a_blocked_user_cannot_receive_an_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.bot_users import block_user

    service = await _setup(seeded_catalog)
    async with async_session_maker() as session:
        await block_user(session, RECIPIENT)
    await _cb(dispatcher, bot, OWNER, f"myservices:xfer:{service.id}")
    await _msg(dispatcher, bot, OWNER, "@new_owner")
    assert "No bot user found" in _last_sent(fake_session, OWNER)["text"]


@pytest.mark.asyncio
async def test_a_username_held_by_several_users_asks_for_the_numeric_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _setup(seeded_catalog)
    async with async_session_maker() as session:
        await seed_bot_user(session, 7009, username="new_owner")
    await _cb(dispatcher, bot, OWNER, f"myservices:xfer:{service.id}")
    await _msg(dispatcher, bot, OWNER, "@new_owner")
    assert "numeric Telegram ID" in _last_sent(fake_session, OWNER)["text"]


@pytest.mark.asyncio
async def test_only_the_owner_can_start_a_transfer(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _setup(seeded_catalog)
    await _cb(dispatcher, bot, STRANGER, f"myservices:xfer:{service.id}")
    await _cb(dispatcher, bot, STRANGER, f"myservices:xferask:{service.id}:{STRANGER + 100}")
    await _cb(dispatcher, bot, STRANGER, f"myservices:xferask:{service.id}:{RECIPIENT}")

    assert _texts_to(fake_session, RECIPIENT) == []
    assert await _owner_of(service.id) == OWNER


# --- The offer and its outcomes -------------------------------------------


@pytest.mark.asyncio
async def test_sending_a_request_offers_the_account_without_moving_it(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.db.models.ownership_transfer import OwnershipTransfer

    service = await _setup(seeded_catalog)
    transfer_id = await _offer(dispatcher, bot, fake_session, service.id)

    offer = _last_sent(fake_session, RECIPIENT)
    assert "@owner_user" in offer["text"] and service.ibsng_username in offer["text"]
    assert _buttons_in(offer) == {"✅ Accept": f"xfer:accept:{transfer_id}", "❌ Decline": f"xfer:decline:{transfer_id}"}
    assert await _owner_of(service.id) == OWNER
    async with async_session_maker() as session:
        row = await session.get(OwnershipTransfer, transfer_id)
    assert row.status == "pending" and row.offer_message_id is not None


@pytest.mark.asyncio
async def test_accepting_moves_the_account_logs_it_and_frees_the_password_reset(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.bot.handlers.ownership as ownership_handler
    from app.db.models.vpn_user import VPNUser

    logged: list[tuple[str, dict]] = []

    async def _log(bot_: Any, key: str, **values: Any) -> None:
        logged.append((key, values))

    monkeypatch.setattr(ownership_handler, "log_event", _log)
    service = await _setup(seeded_catalog)
    async with async_session_maker() as session:
        row = await session.get(VPNUser, service.id)
        row.password_changed_at = dt.datetime.now(dt.timezone.utc)
        await session.commit()
    transfer_id = await _offer(dispatcher, bot, fake_session, service.id)

    await _cb(dispatcher, bot, RECIPIENT, f"xfer:accept:{transfer_id}")

    assert await _owner_of(service.id) == RECIPIENT
    assert any("is now yours" in text for text in _texts_to(fake_session, RECIPIENT))
    assert any("accepted" in text for text in _texts_to(fake_session, OWNER))
    assert logged == [("ownership", {"Account": service.ibsng_username, "From": str(OWNER), "To": str(RECIPIENT)})]
    async with async_session_maker() as session:
        assert (await session.get(VPNUser, service.id)).password_changed_at is None

    # The new owner sees it; the old owner no longer does.
    fake_session.reset()
    await _cb(dispatcher, bot, RECIPIENT, f"myservices:view:{service.id}")
    await _cb(dispatcher, bot, OWNER, f"myservices:view:{service.id}")
    edits = [c[1]["text"] for c in fake_session.calls if c[0] == "editMessageText"]
    assert service.ibsng_username in edits[0]
    assert "not found" in edits[1].lower()


@pytest.mark.asyncio
async def test_declining_leaves_the_account_and_tells_the_owner(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _setup(seeded_catalog)
    transfer_id = await _offer(dispatcher, bot, fake_session, service.id)

    await _cb(dispatcher, bot, RECIPIENT, f"xfer:decline:{transfer_id}")

    assert await _owner_of(service.id) == OWNER
    assert any("declined" in text for text in _texts_to(fake_session, OWNER))
    await _cb(dispatcher, bot, RECIPIENT, f"xfer:accept:{transfer_id}")
    assert await _owner_of(service.id) == OWNER, "a declined offer can't be accepted later"


@pytest.mark.asyncio
async def test_the_owner_can_cancel_and_the_offer_is_withdrawn(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _setup(seeded_catalog)
    transfer_id = await _offer(dispatcher, bot, fake_session, service.id)

    await _cb(dispatcher, bot, OWNER, f"xfer:cancel:{transfer_id}")
    await _cb(dispatcher, bot, RECIPIENT, f"xfer:accept:{transfer_id}")

    assert await _owner_of(service.id) == OWNER
    assert any("cancelled by the owner" in text for text in _texts_to(fake_session, RECIPIENT))


@pytest.mark.asyncio
async def test_nobody_but_the_named_recipient_can_accept(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _setup(seeded_catalog)
    transfer_id = await _offer(dispatcher, bot, fake_session, service.id)

    await _cb(dispatcher, bot, STRANGER, f"xfer:accept:{transfer_id}")
    await _cb(dispatcher, bot, OWNER, f"xfer:accept:{transfer_id}")

    assert await _owner_of(service.id) == OWNER
    await _cb(dispatcher, bot, RECIPIENT, f"xfer:accept:{transfer_id}")
    assert await _owner_of(service.id) == RECIPIENT, "the stray taps did not spoil the real offer"


@pytest.mark.asyncio
async def test_an_offer_older_than_24_hours_cannot_be_accepted(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.db.models.ownership_transfer import OwnershipTransfer

    service = await _setup(seeded_catalog)
    transfer_id = await _offer(dispatcher, bot, fake_session, service.id)
    async with async_session_maker() as session:
        row = await session.get(OwnershipTransfer, transfer_id)
        row.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=25)
        await session.commit()

    await _cb(dispatcher, bot, RECIPIENT, f"xfer:accept:{transfer_id}")

    assert await _owner_of(service.id) == OWNER
    assert any("expired" in text for text in _texts_to(fake_session, RECIPIENT))
    async with async_session_maker() as session:
        assert (await session.get(OwnershipTransfer, transfer_id)).status == "expired"


@pytest.mark.asyncio
async def test_a_newer_request_supersedes_the_older_one(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _setup(seeded_catalog)
    first = await _offer(dispatcher, bot, fake_session, service.id)
    second = await _offer(dispatcher, bot, fake_session, service.id)

    await _cb(dispatcher, bot, RECIPIENT, f"xfer:accept:{first}")
    assert await _owner_of(service.id) == OWNER
    await _cb(dispatcher, bot, RECIPIENT, f"xfer:accept:{second}")
    assert await _owner_of(service.id) == RECIPIENT


@pytest.mark.asyncio
async def test_an_offer_made_stale_by_an_earlier_transfer_cannot_be_accepted(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """The account changed hands by other means after the offer: the
    offering owner no longer owns it, so accepting must do nothing."""
    from app.db.models.vpn_user import VPNUser

    service = await _setup(seeded_catalog)
    transfer_id = await _offer(dispatcher, bot, fake_session, service.id)
    async with async_session_maker() as session:
        row = await session.get(VPNUser, service.id)
        row.telegram_id = STRANGER
        await session.commit()

    await _cb(dispatcher, bot, RECIPIENT, f"xfer:accept:{transfer_id}")
    assert await _owner_of(service.id) == STRANGER


@pytest.mark.asyncio
async def test_an_unreachable_recipient_cancels_the_request(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aiogram.exceptions import TelegramForbiddenError

    from app.db.models.ownership_transfer import OwnershipTransfer

    service = await _setup(seeded_catalog)
    await _cb(dispatcher, bot, OWNER, f"myservices:xfer:{service.id}")
    await _msg(dispatcher, bot, OWNER, "@new_owner")
    send_cb = _buttons_in(_last_sent(fake_session, OWNER))["✅ Send request"]

    original = fake_session.make_request

    async def _blocked(bot_: Any, method: Any, timeout: int | None = None) -> Any:
        if method.__api_method__ == "sendMessage" and method.chat_id == RECIPIENT:
            raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
        return await original(bot_, method, timeout)

    monkeypatch.setattr(fake_session, "make_request", _blocked)
    await _cb(dispatcher, bot, OWNER, send_cb)

    assert any("Couldn't reach" in text for text in _texts_to(fake_session, OWNER))
    async with async_session_maker() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(OwnershipTransfer))).scalars().all()
    assert [r.status for r in rows] == ["cancelled"]


@pytest.mark.asyncio
async def test_the_offer_reaches_a_persian_recipient_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.bot_users import set_language

    service = await _setup(seeded_catalog)
    async with async_session_maker() as session:
        await set_language(session, RECIPIENT, "fa")
    await _offer(dispatcher, bot, fake_session, service.id)

    offer = _last_sent(fake_session, RECIPIENT)
    assert "می‌خواهد اکانت VPN" in offer["text"]
    assert "✅ قبول" in _buttons_in(offer)
