from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.tutorial_admin import (
    BACK_TO_PLATFORM_CB,
    BACK_TO_PROTOCOL_CB,
    BACK_TO_ROOT_CB,
    admin_content_prompt_keyboard,
    admin_platform_keyboard,
    admin_protocol_keyboard,
    tutorial_admin_root_keyboard,
)
from app.bot.states.tutorial_admin import TutorialAdminStates
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.app_config import set_config
from app.services.tutorial_delivery import download_link_key
from app.services.tutorials import list_platforms, list_protocols, upsert_guide, upsert_profile

router = Router(name="tutorial_admin")

_ROOT_TEXT = "📚 Tutorials & Profiles admin:"
_PICK_PROTOCOL_TEXT = "Pick a protocol:"
_PICK_PLATFORM_TEXT = "Pick a platform:"
_SEND_LINK_TEXT = "Send a URL:"
_SEND_MEDIA_TEXT = "Send a photo, document, or video:"
_SEND_PROFILE_TEXT = "Send a photo, document, or video — or type the config text:"
_GUIDE_NEEDS_MEDIA_TEXT = (
    "⚠️ A guide must be a photo, document, or video. Nothing was saved — "
    "the existing guide (if any) is untouched. Please send a file."
)
_PROFILE_NEEDS_CONTENT_TEXT = (
    "⚠️ A profile needs either a file or config text. Nothing was saved — "
    "the existing profile (if any) is untouched. Please send a file or type the config."
)


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


def _content_prompt_text(target: str) -> str:
    if target == "link":
        return _SEND_LINK_TEXT
    return _SEND_PROFILE_TEXT if target == "profile" else _SEND_MEDIA_TEXT


@router.message(Command("admintutorials"))
async def admin_root_cmd(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    # Re-issuing the command is also the flow's hard reset - drop any
    # half-finished FSM state so the new run can't inherit a stale target.
    await state.clear()
    await message.answer(_ROOT_TEXT, reply_markup=tutorial_admin_root_keyboard())


# Registered BEFORE the state-filtered pickers below: those match any
# "tutadm:"-prefixed callback in their state and would try to parse a
# back-navigation callback as a protocol/platform id.
@router.callback_query(F.data == BACK_TO_ROOT_CB)
async def admin_back_to_root_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_ROOT_TEXT, reply_markup=tutorial_admin_root_keyboard())
    await callback.answer()


@router.callback_query(F.data == BACK_TO_PROTOCOL_CB)
async def admin_back_to_protocol_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    data = await state.get_data()
    target = data.get("target")
    if target is None:
        await admin_back_to_root_cb(callback, state)
        return
    await state.set_state(TutorialAdminStates.pick_protocol)
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(
            _PICK_PROTOCOL_TEXT, reply_markup=admin_protocol_keyboard(protocols, target=target)
        )
    await callback.answer()


@router.callback_query(F.data == BACK_TO_PLATFORM_CB)
async def admin_back_to_platform_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    data = await state.get_data()
    target, protocol_id = data.get("target"), data.get("protocol_id")
    if target is None or protocol_id is None:
        await admin_back_to_root_cb(callback, state)
        return
    await state.set_state(TutorialAdminStates.pick_platform)
    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)
        platforms = await list_platforms(session)
    allow_generic = protocol is not None and protocol.label.strip().lower() == "openvpn"
    if callback.message is not None:
        await callback.message.edit_text(
            _PICK_PLATFORM_TEXT,
            reply_markup=admin_platform_keyboard(platforms, target=target, allow_generic=allow_generic),
        )
    await callback.answer()


@router.callback_query(F.data.in_({"tutadm:guide", "tutadm:profile", "tutadm:link"}))
async def admin_pick_target_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    target = callback.data.split(":")[1]
    await state.set_state(TutorialAdminStates.pick_protocol)
    await state.update_data(target=target)
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(
            _PICK_PROTOCOL_TEXT, reply_markup=admin_protocol_keyboard(protocols, target=target)
        )
    await callback.answer()


@router.callback_query(TutorialAdminStates.pick_protocol, F.data.startswith("tutadm:"))
async def admin_pick_protocol_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, target, _kind, protocol_id_str = callback.data.split(":")
    protocol_id = int(protocol_id_str)
    await state.update_data(protocol_id=protocol_id)

    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)
        protocol_label = protocol.label if protocol is not None else ""
        platforms = await list_platforms(session)

    # OpenVPN profiles/guides/links may be generic (no platform); L2TP
    # always needs a specific platform.
    allow_generic = protocol_label.strip().lower() == "openvpn"
    await state.set_state(TutorialAdminStates.pick_platform)
    if callback.message is not None:
        await callback.message.edit_text(
            _PICK_PLATFORM_TEXT,
            reply_markup=admin_platform_keyboard(platforms, target=target, allow_generic=allow_generic),
        )
    await callback.answer()


@router.callback_query(TutorialAdminStates.pick_platform, F.data.startswith("tutadm:"))
async def admin_pick_platform_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    platform_id_str = parts[-1]
    platform_id = None if platform_id_str == "none" else int(platform_id_str)
    await state.update_data(platform_id=platform_id)
    await state.set_state(TutorialAdminStates.await_content)
    if callback.message is not None:
        data = await state.get_data()
        await callback.message.edit_text(
            _content_prompt_text(data["target"]), reply_markup=admin_content_prompt_keyboard()
        )
    await callback.answer()


@router.message(TutorialAdminStates.await_content)
async def admin_receive_content(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    target, protocol_id, platform_id = data["target"], data["protocol_id"], data["platform_id"]

    text = (message.text or "").strip()

    if target == "link":
        await state.clear()
        async with async_session_maker() as session:
            protocol = await session.get(TutorialProtocol, protocol_id)
            platform = await session.get(TutorialPlatform, platform_id) if platform_id is not None else None
            await set_config(
                session,
                download_link_key(
                    protocol_label=protocol.label, platform_label=platform.label if platform is not None else None
                ),
                text,
            )
        await message.answer("✅ Download link saved.")
        return

    file_id: str | None = None
    file_type: str | None = None
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    elif message.document:
        file_id, file_type = message.document.file_id, "document"
    elif message.video:
        file_id, file_type = message.video.file_id, "video"

    # Reject empty content rather than writing it: upsert_guide with
    # media_file_id=None would silently blank out a guide that is already
    # configured (guides are media-only from this flow - there is no
    # body_html input), and an all-NULL profile row is equally useless.
    # Staying in await_content lets the admin simply resend.
    if target == "guide" and file_id is None:
        await message.answer(_GUIDE_NEEDS_MEDIA_TEXT, reply_markup=admin_content_prompt_keyboard())
        return
    if target == "profile" and file_id is None and not text:
        await message.answer(_PROFILE_NEEDS_CONTENT_TEXT, reply_markup=admin_content_prompt_keyboard())
        return

    await state.clear()
    async with async_session_maker() as session:
        if target == "guide":
            await upsert_guide(
                session, platform_id=platform_id, protocol_id=protocol_id, media_file_id=file_id, media_type=file_type
            )
        else:
            # A text-only profile is a designed option (OpenVpnProfile.text),
            # so plain config text is accepted here - unlike for a guide.
            await upsert_profile(
                session, platform_id=platform_id, name=f"Profile {protocol_id}/{platform_id}",
                file_id=file_id, file_type=file_type, text=text if file_id is None else None,
            )
    await message.answer("✅ Saved.")
