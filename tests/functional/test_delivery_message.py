"""The one account-delivery message, exercised directly.

Three flows send it - purchase, renewal and trial - and the point of the
shared template is that only the headline differs, so these tests assert
the body is identical whichever flow asked for it.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.fakes.fake_bot_session import FakeBotSession


async def _plan(seeded_catalog: dict, *, category: str, name: str):  # type: ignore[no-untyped-def]
    from app.services.catalog import get_plan

    plan_id = next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)
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
    ],
)
async def test_every_paid_flow_sends_the_same_body_under_its_own_headline(
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
    assert "<b>Plan:</b> 1 Month" in text
    assert "30 days from first connection" in text
    assert "<b>Volume:</b> 10 GB" in text
    # Separate spans: tap-to-copy works per span, so one combined block
    # would force the customer to hand-edit the credentials apart.
    assert "<code>ir.abc123</code>" in text
    assert "<code>pw1234</code>" in text
    # Step 3 of the shared handover: the Tutorial/Back pair ends the
    # sequence, so the credentials carry neither the pair nor a pointer.
    assert "Tutorial section" not in text
    assert "reply_markup" not in payload


@pytest.mark.asyncio
async def test_the_trial_message_has_no_tutorial_note_and_no_buttons(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """The trial's credentials are one step of a longer sequence; its
    Tutorial/Back pair goes on that sequence's last message instead, and
    the paragraph pointing at the Tutorial section is dropped for it."""
    from app.services.delivery import TRIAL, send_account_delivery

    trial = await _plan(seeded_catalog, category="trial", name="Trial")
    message_id = await send_account_delivery(
        bot, 3009, kind=TRIAL, plan=trial, data_cap_mb=trial.data_cap_mb,
        username="ir.t00009", password="pw9", lang="en",
    )

    payload = _last_message(fake_session)
    assert "Your trial service is ready" in payload["text"]
    assert "<code>ir.t00009</code>" in payload["text"] and "<code>pw9</code>" in payload["text"]
    assert "Tutorial section" not in payload["text"]
    assert "reply_markup" not in payload
    assert isinstance(message_id, int)


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
    """Checked against the seeded catalog rather than assumed: a trial is
    a real Plan row (1 day, 1024 MB), not a special case."""
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
    assert "<b>پلن خریداری‌شده:</b> تست رایگان" in text
    assert "بخش «آموزش»" not in text
    assert "reply_markup" not in payload

    monthly = await _plan(seeded_catalog, category="scroll", name="1 Month")
    await send_account_delivery(
        bot, 3004, kind="purchase", plan=monthly, data_cap_mb=10240,
        username="ir.p00003", password="pw", lang="fa",
    )
    payload = _last_message(fake_session)
    assert "سفارش شما با موفقیت ثبت شد" in payload["text"]
    assert "بخش «آموزش»" not in payload["text"]
    assert "reply_markup" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["purchase", "renewal", "trial"])
async def test_missing_password_still_delivers_with_the_username(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, kind: str
) -> None:
    """The account IS provisioned - an unreadable password must degrade
    to the contact-support variant on every flow, never look like a
    failure."""
    from app.services.delivery import send_account_delivery

    plan = await _plan(seeded_catalog, category="scroll", name="1 Month")
    await send_account_delivery(
        bot, 3005, kind=kind, plan=plan, data_cap_mb=10240,
        username="ir.nopass", password=None, lang="en",
    )

    text = _last_message(fake_session)["text"]
    assert "contact support" in text.lower()
    assert "<code>ir.nopass</code>" in text


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
    """The account is provisioned either way - a blocked customer must
    not turn into a failure the caller has to handle."""
    from app.services.delivery import send_account_delivery

    plan = await _plan(seeded_catalog, category="scroll", name="1 Month")
    fake_session.blocked_chat_ids.add(3007)

    await send_account_delivery(
        bot, 3007, kind="purchase", plan=plan, data_cap_mb=10240,
        username="ir.blocked", password="pw", lang="en",
    )


@pytest.mark.asyncio
async def test_a_missing_plan_falls_back_to_the_group_name(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """A payment whose plan row was deleted must still deliver something
    meaningful rather than crashing on a None."""
    from app.services.delivery import send_account_delivery

    await send_account_delivery(
        bot, 3008, kind="purchase", plan=None, data_cap_mb=5120,
        username="ir.noplan", password="pw", lang="en",
        fallback_plan_name="2W-1U-Iran-5G",
    )

    text = _last_message(fake_session)["text"]
    assert "2W-1U-Iran-5G" in text
    assert "<code>ir.noplan</code>" in text
