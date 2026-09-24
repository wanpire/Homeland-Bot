"""My Services' Change Ownership flow - an offer the recipient accepts.

Thin by design: parsing and rendering here, every rule in
app/services/ownership.py. See
docs/superpowers/specs/2026-09-25-change-ownership-design.md.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.myservices import back_to_account_keyboard
from app.bot.keyboards.ownership import (
    to_my_services_keyboard,
    transfer_confirm_keyboard,
    transfer_offer_keyboard,
    transfer_pending_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.bot.states.ownership import OwnershipStates
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.adminlog import OWNERSHIP, log_event
from app.services.bot_users import get_language
from app.services.catalog import get_plan, plan_display_name
from app.services.ownership import (
    AMBIGUOUS,
    EXPIRED,
    NOT_FOUND,
    SELF,
    Settled,
    accept_transfer,
    cancel_transfer,
    create_transfer,
    decline_transfer,
    display_name,
    get_bot_user,
    mark_unreachable,
    record_offer_message,
    resolve_recipient,
)
from app.services.vpn_users import get_owned_vpn_user

router = Router(name="ownership")

logger = logging.getLogger(__name__)

_RESOLVE_ERRORS = {NOT_FOUND: "xfer_not_found", SELF: "xfer_self", AMBIGUOUS: "xfer_ambiguous"}


def _ints(data: str, start: int, count: int) -> list[int] | None:
    parts = data.split(":")
    try:
        values = [int(p) for p in parts[start:start + count]]
    except ValueError:
        return None
    if len(values) != count or not all(0 < v < 2**63 for v in values):
        return None
    return values


async def _name_of(telegram_id: int, lang: str) -> str:
    async with async_session_maker() as session:
        bot_user = await get_bot_user(session, telegram_id)
    return display_name(bot_user, t("xfer_user_id", lang, telegram_id=telegram_id))


async def _lang_of(telegram_id: int) -> str:
    async with async_session_maker() as session:
        return (await get_language(session, telegram_id)) or "en"


async def _tell(bot: Bot, telegram_id: int, text: str) -> None:
    try:
        await bot.send_message(telegram_id, text)
    except TelegramAPIError:
        logger.warning("Ownership: could not notify %s", telegram_id)


async def _not_found(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        await callback.message.edit_text(t("myservices_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data.startswith("myservices:xfer:"))
async def transfer_start_cb(callback: CallbackQuery, lang: str, state: FSMContext) -> None:
    ids = _ints(callback.data, 2, 1)
    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, ids[0], callback.from_user.id) if ids and ids[0] < 2**31 else None
    if vpn_user is None:
        await _not_found(callback, lang)
        return
    await state.set_state(OwnershipStates.recipient)
    await state.update_data(vpn_user_id=vpn_user.id)
    if callback.message is not None:
        await callback.message.edit_text(
            t("xfer_prompt", lang, username=vpn_user.ibsng_username),
            reply_markup=back_to_account_keyboard(vpn_user.id, lang),
        )
    await callback.answer()


@router.message(OwnershipStates.recipient)
async def transfer_recipient_msg(message: Message, lang: str, state: FSMContext) -> None:
    vpn_user_id = (await state.get_data()).get("vpn_user_id")
    owner_id = message.from_user.id
    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, owner_id) if vpn_user_id else None
        if vpn_user is None:
            await state.clear()
            await message.answer(t("myservices_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
            return
        recipient = await resolve_recipient(session, message.text or "", owner_telegram_id=owner_id)

    if isinstance(recipient, str):
        await message.answer(t(_RESOLVE_ERRORS[recipient], lang), reply_markup=back_to_account_keyboard(vpn_user.id, lang))
        return

    # The recipient travels in the confirm button and is re-validated on
    # the tap, so the prompt state is no longer needed.
    await state.clear()
    name = display_name(recipient, t("xfer_user_id", lang, telegram_id=recipient.telegram_id))
    await message.answer(
        t("xfer_confirm", lang, username=vpn_user.ibsng_username, recipient=name),
        reply_markup=transfer_confirm_keyboard(vpn_user.id, recipient.telegram_id, lang),
    )


@router.callback_query(F.data.startswith("myservices:xferask:"))
async def transfer_request_cb(callback: CallbackQuery, lang: str) -> None:
    ids = _ints(callback.data, 2, 2)
    owner_id = callback.from_user.id
    if ids is None or ids[0] >= 2**31:
        await _not_found(callback, lang)
        return
    vpn_user_id, recipient_id = ids

    async with async_session_maker() as session:
        recipient = await resolve_recipient(session, str(recipient_id), owner_telegram_id=owner_id)
        if isinstance(recipient, str):
            if callback.message is not None:
                await callback.message.edit_text(
                    t(_RESOLVE_ERRORS[recipient], lang), reply_markup=back_to_account_keyboard(vpn_user_id, lang)
                )
            await callback.answer()
            return
        transfer = await create_transfer(
            session, vpn_user_id=vpn_user_id, owner_telegram_id=owner_id, recipient_telegram_id=recipient_id
        )
        if transfer is None:
            await _not_found(callback, lang)
            return
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, owner_id)
        plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None

    recipient_lang = await _lang_of(recipient_id)
    recipient_name = display_name(recipient, t("xfer_user_id", lang, telegram_id=recipient_id))
    try:
        offer = await callback.bot.send_message(
            recipient_id,
            t(
                "xfer_offer", recipient_lang,
                owner=await _name_of(owner_id, recipient_lang),
                username=vpn_user.ibsng_username,
                plan=plan_display_name(plan, recipient_lang) if plan is not None else vpn_user.ibsng_group,
            ),
            reply_markup=transfer_offer_keyboard(transfer.id, recipient_lang),
        )
    except TelegramAPIError:
        logger.warning("Ownership: offer %s could not reach %s", transfer.id, recipient_id)
        async with async_session_maker() as session:
            await mark_unreachable(session, transfer.id)
        if callback.message is not None:
            await callback.message.edit_text(
                t("xfer_unreachable", lang, recipient=recipient_name),
                reply_markup=back_to_account_keyboard(vpn_user_id, lang),
            )
        await callback.answer()
        return

    async with async_session_maker() as session:
        await record_offer_message(session, transfer.id, offer.message_id)
    if callback.message is not None:
        await callback.message.edit_text(
            t("xfer_sent", lang, recipient=recipient_name, username=vpn_user.ibsng_username),
            reply_markup=transfer_pending_keyboard(transfer.id, vpn_user_id, lang),
        )
    await callback.answer()


async def _answer_stale(callback: CallbackQuery, settled: Settled, lang: str) -> None:
    """The tap found nothing to do: tell the tapper why, and remove the
    dead buttons."""
    key = "xfer_expired" if settled.status == EXPIRED else "xfer_invalid"
    if callback.message is not None:
        try:
            await callback.message.edit_text(t(key, lang))
        except TelegramAPIError:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("xfer:accept:"))
async def transfer_accept_cb(callback: CallbackQuery, lang: str) -> None:
    ids = _ints(callback.data, 2, 1)
    if ids is None or ids[0] >= 2**31:
        await callback.answer()
        return
    async with async_session_maker() as session:
        settled = await accept_transfer(session, transfer_id=ids[0], telegram_id=callback.from_user.id)
    if not settled.changed:
        await _answer_stale(callback, settled, lang)
        return

    transfer, vpn_user = settled.transfer, settled.vpn_user
    username = vpn_user.ibsng_username
    if callback.message is not None:
        await callback.message.edit_text(
            t("xfer_accepted_recipient", lang, username=username), reply_markup=to_my_services_keyboard(lang)
        )
    owner_lang = await _lang_of(transfer.from_telegram_id)
    await _tell(
        callback.bot, transfer.from_telegram_id,
        t("xfer_accepted_owner", owner_lang, recipient=await _name_of(transfer.to_telegram_id, owner_lang), username=username),
    )
    await log_event(
        callback.bot, OWNERSHIP,
        Account=username, From=str(transfer.from_telegram_id), To=str(transfer.to_telegram_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("xfer:decline:"))
async def transfer_decline_cb(callback: CallbackQuery, lang: str) -> None:
    ids = _ints(callback.data, 2, 1)
    if ids is None or ids[0] >= 2**31:
        await callback.answer()
        return
    async with async_session_maker() as session:
        settled = await decline_transfer(session, transfer_id=ids[0], telegram_id=callback.from_user.id)
    if not settled.changed:
        await _answer_stale(callback, settled, lang)
        return
    transfer = settled.transfer
    if callback.message is not None:
        await callback.message.edit_text(t("xfer_declined_recipient", lang))
    owner_lang = await _lang_of(transfer.from_telegram_id)
    await _tell(
        callback.bot, transfer.from_telegram_id,
        t(
            "xfer_declined_owner", owner_lang,
            recipient=await _name_of(transfer.to_telegram_id, owner_lang),
            username=settled.vpn_user.ibsng_username,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("xfer:cancel:"))
async def transfer_cancel_cb(callback: CallbackQuery, lang: str) -> None:
    ids = _ints(callback.data, 2, 1)
    if ids is None or ids[0] >= 2**31:
        await callback.answer()
        return
    async with async_session_maker() as session:
        settled = await cancel_transfer(session, transfer_id=ids[0], telegram_id=callback.from_user.id)
    if not settled.changed:
        await _answer_stale(callback, settled, lang)
        return
    transfer, vpn_user = settled.transfer, settled.vpn_user
    if callback.message is not None:
        await callback.message.edit_text(
            t("xfer_cancelled_owner", lang, username=vpn_user.ibsng_username),
            reply_markup=back_to_account_keyboard(vpn_user.id, lang),
        )
    if transfer.offer_message_id is not None:
        recipient_lang = await _lang_of(transfer.to_telegram_id)
        try:
            await callback.bot.edit_message_text(
                t("xfer_cancelled_recipient", recipient_lang),
                chat_id=transfer.to_telegram_id,
                message_id=transfer.offer_message_id,
            )
        except TelegramAPIError:
            logger.warning("Ownership: could not withdraw offer %s", transfer.id)
    await callback.answer()
