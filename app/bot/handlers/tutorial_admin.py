from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.tutorial_admin import admin_platform_keyboard, admin_protocol_keyboard, tutorial_admin_root_keyboard
from app.bot.states.tutorial_admin import TutorialAdminStates
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.app_config import set_config
from app.services.tutorials import list_platforms, list_protocols, upsert_guide, upsert_profile

router = Router(name="tutorial_admin")


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


@router.message(Command("admintutorials"))
async def admin_root_cmd(message: Message) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    await message.answer("📚 Tutorials & Profiles admin:", reply_markup=tutorial_admin_root_keyboard())


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
        await callback.message.edit_text("Pick a protocol:", reply_markup=admin_protocol_keyboard(protocols, target=target))
    await callback.answer()


@router.callback_query(TutorialAdminStates.pick_protocol, F.data.startswith("tutadm:"))
async def admin_pick_protocol_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, target, _kind, protocol_id_str = callback.data.split(":")
    protocol_id = int(protocol_id_str)
    await state.update_data(protocol_id=protocol_id)

    protocol_label = None
    async with async_session_maker() as session:
        from app.db.models.tutorial_protocol import TutorialProtocol

        protocol = await session.get(TutorialProtocol, protocol_id)
        protocol_label = protocol.label if protocol is not None else ""
        platforms = await list_platforms(session)

    # OpenVPN profiles/guides/links may be generic (no platform); L2TP
    # always needs a specific platform.
    allow_generic = protocol_label.strip().lower() == "openvpn"
    await state.set_state(TutorialAdminStates.pick_platform)
    if callback.message is not None:
        await callback.message.edit_text(
            "Pick a platform:", reply_markup=admin_platform_keyboard(platforms, target=target, allow_generic=allow_generic)
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
        prompt = "Send a URL:" if data["target"] == "link" else "Send a photo, document, or video:"
        await callback.message.edit_text(prompt)
    await callback.answer()


@router.message(TutorialAdminStates.await_content)
async def admin_receive_content(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    target, protocol_id, platform_id = data["target"], data["protocol_id"], data["platform_id"]
    await state.clear()

    if target == "link":
        url = (message.text or "").strip()
        async with async_session_maker() as session:
            from app.db.models.tutorial_platform import TutorialPlatform
            from app.db.models.tutorial_protocol import TutorialProtocol

            protocol = await session.get(TutorialProtocol, protocol_id)
            platform = await session.get(TutorialPlatform, platform_id) if platform_id is not None else None
            platform_key = platform.label.strip().lower() if platform is not None else "any"
            await set_config(session, f"download_link:{protocol.label.strip().lower()}:{platform_key}", url)
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

    async with async_session_maker() as session:
        if target == "guide":
            await upsert_guide(session, platform_id=platform_id, protocol_id=protocol_id, media_file_id=file_id, media_type=file_type)
        else:
            await upsert_profile(
                session, platform_id=platform_id, name=f"Profile {protocol_id}/{platform_id}",
                file_id=file_id, file_type=file_type, text=message.text if file_id is None else None,
            )
    await message.answer("✅ Saved.")
