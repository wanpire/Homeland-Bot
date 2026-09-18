from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.fakes.fake_bot_session import FakeBotSession


async def _seed_vpn_user(
    telegram_id: int, *, is_trial: bool = False, expiry_reminder_sent_at: dt.datetime | None = None
) -> None:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(
            VPNUser(
                telegram_id=telegram_id,
                ibsng_username=f"hl.rem{telegram_id}",
                ibsng_group="Trial-Iran",
                data_cap_mb=1024,
                is_trial=is_trial,
                expiry_reminder_sent_at=expiry_reminder_sent_at,
            )
        )
        await session.commit()


def _patch_status(monkeypatch: pytest.MonkeyPatch, status: str, expiry: dt.datetime | None) -> None:
    from app.services import reminders

    async def _fake_get_service_status(client: object, username: str) -> tuple[str, dt.datetime | None]:
        return status, expiry

    monkeypatch.setattr(reminders, "get_service_status", _fake_get_service_status)


def _sent(fake_session: FakeBotSession) -> list[tuple[str, dict[str, Any]]]:
    return [c for c in fake_session.calls if c[0] == "sendMessage"]


@pytest.mark.asyncio
async def test_sends_reminder_for_user_within_default_window(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(701)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)

    await send_due_reminders(bot)

    sent = _sent(fake_session)
    assert len(sent) == 1
    assert sent[0][1]["chat_id"] == 701
    assert "expires" in sent[0][1]["text"].lower()
    buttons = [b for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["text"] == "♻️ Renew Now" and b["callback_data"] == "menu:renew" for b in buttons)


@pytest.mark.asyncio
async def test_stamps_expiry_reminder_sent_at(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(702)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)

    await send_due_reminders(bot)

    async with async_session_maker() as session:
        vpn_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 702))).scalar_one()
    assert vpn_user.expiry_reminder_sent_at is not None


@pytest.mark.asyncio
async def test_does_not_send_when_disabled(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.app_config import set_config
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(703)
    _patch_status(monkeypatch, "active", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    async with async_session_maker() as session:
        await set_config(session, "reminder_enabled", "false")

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
async def test_unset_reminder_enabled_defaults_to_enabled(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.app_config import get_config
    from app.services.reminders import send_due_reminders

    async with async_session_maker() as session:
        assert await get_config(session, "reminder_enabled") is None

    await _seed_vpn_user(704)
    _patch_status(monkeypatch, "active", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))

    await send_due_reminders(bot)

    assert len(_sent(fake_session)) == 1


@pytest.mark.asyncio
async def test_skips_user_already_reminded_this_cycle(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(705, expiry_reminder_sent_at=dt.datetime.now(dt.timezone.utc))
    _patch_status(monkeypatch, "active", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
async def test_skips_trial_accounts(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(706, is_trial=True)
    _patch_status(monkeypatch, "active", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "unknown", "expired"])
async def test_skips_non_active_status(
    status: str, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(707)
    expiry = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1) if status == "expired" else None
    _patch_status(monkeypatch, status, expiry)

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
async def test_skips_user_outside_default_window(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(708)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)
    _patch_status(monkeypatch, "active", expiry)

    await send_due_reminders(bot)

    assert _sent(fake_session) == []


@pytest.mark.asyncio
async def test_respects_configured_days_before_threshold(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.app_config import set_config
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(709)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=4)
    _patch_status(monkeypatch, "active", expiry)
    async with async_session_maker() as session:
        await set_config(session, "reminder_days_before", "5")

    await send_due_reminders(bot)

    assert len(_sent(fake_session)) == 1


@pytest.mark.asyncio
async def test_one_users_send_failure_does_not_abort_the_batch(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(710)
    await _seed_vpn_user(711)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)
    fake_session.blocked_chat_ids.add(710)

    await send_due_reminders(bot)

    sent = _sent(fake_session)
    assert len(sent) == 1
    assert sent[0][1]["chat_id"] == 711

    async with async_session_maker() as session:
        blocked_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 710))).scalar_one()
        delivered_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 711))).scalar_one()
    assert blocked_user.expiry_reminder_sent_at is None
    assert delivered_user.expiry_reminder_sent_at is not None


@pytest.mark.asyncio
async def test_one_users_lookup_exception_does_not_abort_the_batch(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-IBSngError exception from get_service_status (malformed
    XML-RPC response, unexpected payload shape, ...) for one candidate
    must not kill the loop and skip every remaining candidate."""
    from app.services import reminders
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(720)
    await _seed_vpn_user(721)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)

    async def _fake_get_service_status(client: object, username: str) -> tuple[str, dt.datetime | None]:
        if username == "hl.rem720":
            raise RuntimeError("malformed XML-RPC response")
        return "active", expiry

    monkeypatch.setattr(reminders, "get_service_status", _fake_get_service_status)

    await send_due_reminders(bot)

    sent = _sent(fake_session)
    assert len(sent) == 1
    assert sent[0][1]["chat_id"] == 721


@pytest.mark.asyncio
async def test_absurdly_large_days_before_does_not_crash_the_job(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.app_config import set_config
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(722)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)
    async with async_session_maker() as session:
        await set_config(session, "reminder_days_before", "999999999999")

    await send_due_reminders(bot)  # must not raise OverflowError

    assert len(_sent(fake_session)) == 1


@pytest.mark.asyncio
async def test_blocked_user_does_not_receive_reminder(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.bot_user import BotUser

    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(723)
    await _seed_vpn_user(724)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)

    async with async_session_maker() as session:
        session.add(BotUser(telegram_id=723, is_blocked=True))
        await session.commit()

    await send_due_reminders(bot)

    sent = _sent(fake_session)
    assert len(sent) == 1
    assert sent[0][1]["chat_id"] == 724


@pytest.mark.asyncio
async def test_expired_status_stamps_reminder_sent_at_without_sending(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(725)
    expiry = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    _patch_status(monkeypatch, "expired", expiry)

    await send_due_reminders(bot)

    assert _sent(fake_session) == []
    async with async_session_maker() as session:
        vpn_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 725))).scalar_one()
    assert vpn_user.expiry_reminder_sent_at is not None


@pytest.mark.asyncio
async def test_run_reminder_loop_calls_send_due_reminders_each_iteration(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import reminders

    calls: list[object] = []

    async def _fake_send_due_reminders(bot: object) -> None:
        calls.append(bot)

    class _StopLoop(Exception):
        pass

    async def _fake_sleep(seconds: float) -> None:
        raise _StopLoop()

    monkeypatch.setattr(reminders, "send_due_reminders", _fake_send_due_reminders)
    monkeypatch.setattr(reminders.asyncio, "sleep", _fake_sleep)

    fake_bot = object()
    with pytest.raises(_StopLoop):
        await reminders.run_reminder_loop(fake_bot)  # type: ignore[arg-type]

    assert calls == [fake_bot]


@pytest.mark.asyncio
async def test_run_reminder_loop_survives_an_iteration_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import reminders

    calls: list[object] = []

    async def _boom(bot: object) -> None:
        calls.append(bot)
        raise RuntimeError("boom")

    class _StopLoop(Exception):
        pass

    async def _fake_sleep(seconds: float) -> None:
        raise _StopLoop()

    monkeypatch.setattr(reminders, "send_due_reminders", _boom)
    monkeypatch.setattr(reminders.asyncio, "sleep", _fake_sleep)

    with pytest.raises(_StopLoop):
        await reminders.run_reminder_loop(object())  # type: ignore[arg-type]

    assert len(calls) == 1


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


@pytest.mark.asyncio
async def test_language_lookup_failure_defaults_to_english_and_continues_batch(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When get_language raises for one candidate, that candidate should
    still receive their reminder (in English as a safe default), and the
    batch should continue processing any other candidates normally.

    The fake get_language below deliberately issues a real failing
    statement THROUGH THE ACTUAL SESSION reminders.py's batch loop is
    running on, rather than a bare exception that never touches the
    session. That distinction matters: a bare RuntimeError (this test's
    previous version) never leaves the session needing a rollback, so it
    can't actually prove app/services/reminders.py's `await
    session.rollback()` fix does anything - the test passed before that
    fix existed too. A genuine DBAPI error against the real session does
    leave it needing a rollback, so this version actually exercises the
    fix: without it, the second candidate's later `await session.commit()`
    would raise PendingRollbackError and abort the rest of the batch.
    Asserting the SECOND candidate's expiry_reminder_sent_at is actually
    persisted in the DB (not just that bot.send_message was called) proves
    the session itself is still usable afterward, which is the real
    property being fixed."""
    import datetime as dt

    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models.vpn_user import VPNUser
    from app.services import reminders
    from app.services.reminders import send_due_reminders

    await _seed_vpn_user(760)
    await _seed_vpn_user(761)
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    _patch_status(monkeypatch, "active", expiry)

    async def _fake_get_language(session: AsyncSession, telegram_id: int) -> str | None:
        if telegram_id == 760:
            # A genuine DBAPI-level failure using the SAME session the
            # batch loop holds open - this is what actually poisons the
            # transaction, unlike an exception that bypasses the session
            # entirely.
            await session.execute(sa_text("SELECT 1/0"))
        return None  # 761 has no language set, defaults to English

    monkeypatch.setattr(reminders, "get_language", _fake_get_language)

    await send_due_reminders(bot)

    sent = _sent(fake_session)
    assert len(sent) == 2  # Both candidates should receive reminders

    # Both should be in English (760 due to fallback, 761 due to no language set)
    assert all("expires" in s[1]["text"].lower() for s in sent)
    assert all(
        any(b["text"] == "♻️ Renew Now" for row in s[1]["reply_markup"]["inline_keyboard"] for b in row)
        for s in sent
    )

    # Proves the session survived the failure and is still usable for the
    # rest of the batch, not just that send_message happened to fire
    # before some later step silently failed.
    async with async_session_maker() as session:
        second = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 761))).scalar_one()
    assert second.expiry_reminder_sent_at is not None
