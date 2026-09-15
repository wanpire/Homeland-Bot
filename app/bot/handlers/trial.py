from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.bot.keyboards.trial import back_to_menu_keyboard, trial_confirm_keyboard, trial_platform_keyboard, trial_protocol_keyboard
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import list_plans
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols
from app.services.vpn_users import VPNUsernameTakenError, create_vpn_user, generate_vpn_credentials, has_used_trial

router = Router(name="trial")

_ALREADY_USED_TEXT = "🎁 You've already used your free trial."
_CONFIRM_TEXT = "🎁 <b>Free Trial</b> — 24 hours, 1GB of data.\n\nStart your trial?"
_CREATE_FAILED_TEXT = "⚠️ Couldn't create your trial right now. Please try again shortly."
_MAX_CREATE_ATTEMPTS = 3


async def _send_trial_credentials(bot: Bot, telegram_id: int) -> None:
    """deliver_setup (Task 3) deliberately does NOT send the account's
    username/password - it's a generic (platform, protocol) -> content
    function reused later by Buy/Renew, which won't always want the
    same trial-specific closing message. The credentials themselves were
    generated back in trial_confirm_cb, a separate callback invocation
    with nothing carried forward (no FSM state, by design - see the
    spec's rationale for not putting a password in callback_data), so
    they're looked up fresh here: the just-created VPNUser row gives the
    username, and IBSngClient.get_user_password re-reads the password
    IBSng already has stored for it (same accessor AloBot's own renew
    flow uses to re-show an existing password)."""
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

    async with IBSngClient() as client:
        password = await client.get_user_password(username=vpn_user.ibsng_username)

    await bot.send_message(
        telegram_id,
        "🎁 <b>Your trial is ready.</b>\n\n"
        f"Username: <code>{vpn_user.ibsng_username}</code>\n"
        f"Password: <code>{password}</code>\n\n"
        "⏱ Valid for 24 hours from first connection.",
    )


@router.callback_query(F.data == "menu:trial")
async def trial_entry_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        already_used = await has_used_trial(session, callback.from_user.id)

    if callback.message is None:
        await callback.answer()
        return
    if already_used:
        await callback.message.edit_text(_ALREADY_USED_TEXT, reply_markup=back_to_menu_keyboard())
    else:
        await callback.message.edit_text(_CONFIRM_TEXT, reply_markup=trial_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data == "trial:confirm")
async def trial_confirm_cb(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        trial_plans = await list_plans(session, category="trial")
    trial_plan = trial_plans[0]

    vpn_user = None
    last_error: str | None = None
    for _attempt in range(_MAX_CREATE_ATTEMPTS):
        username, password = generate_vpn_credentials()
        async with async_session_maker() as session, IBSngClient() as client:
            try:
                vpn_user = await create_vpn_user(
                    session, client,
                    telegram_id=telegram_id, username=username, password=password,
                    group_name=trial_plan.group_name, data_cap_mb=trial_plan.data_cap_mb,
                    plan_id=trial_plan.id, is_trial=True,
                )
                break
            except (VPNUsernameTakenError, IBSngUserExistsError):
                last_error = "taken"
                continue
            except IBSngError:
                last_error = "ibsng"
                break

    if vpn_user is None:
        if callback.message is not None:
            text = _ALREADY_USED_TEXT if last_error == "taken" else _CREATE_FAILED_TEXT
            await callback.message.edit_text(text, reply_markup=back_to_menu_keyboard())
        await callback.answer()
        return

    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(
            "🔌 Which protocol do you want to use?", reply_markup=trial_protocol_keyboard(protocols)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("trial:protocol:"))
async def trial_protocol_cb(callback: CallbackQuery) -> None:
    protocol_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)

    if protocol is not None and protocol.label.strip().lower() == "openvpn":
        async with async_session_maker() as session:
            delivered, _ = await deliver_setup(callback.bot, callback.from_user.id, session, protocol_id=protocol_id, platform_id=None)
        if delivered:
            await _send_trial_credentials(callback.bot, callback.from_user.id)
        await callback.answer()
        return

    async with async_session_maker() as session:
        platforms = await list_platforms(session)
    if callback.message is not None:
        await callback.message.edit_text(
            "📱 Which device do you want to set it up on?",
            reply_markup=trial_platform_keyboard(platforms),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("trial:platform:"))
async def trial_platform_cb(callback: CallbackQuery) -> None:
    platform_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    l2tp = next(p for p in protocols if p.label.strip().lower() == "l2tp")

    async with async_session_maker() as session:
        delivered, _ = await deliver_setup(callback.bot, callback.from_user.id, session, protocol_id=l2tp.id, platform_id=platform_id)
    if delivered:
        await _send_trial_credentials(callback.bot, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "trial:back_to_protocol")
async def trial_back_to_protocol_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text("🔌 Which protocol do you want to use?", reply_markup=trial_protocol_keyboard(protocols))
    await callback.answer()
