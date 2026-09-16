from __future__ import annotations

import html
from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsSalesAdmin
from app.bot.keyboards.admin_discounts import (
    discount_delete_confirm_keyboard,
    discount_detail_keyboard,
    discount_list_keyboard,
    wizard_cancel_keyboard,
    wizard_plans_keyboard,
    wizard_usage_limit_keyboard,
    wizard_visibility_keyboard,
)
from app.bot.states.admin_discounts import DiscountCodeStates
from app.db.models.discount_code import DiscountCode
from app.db.session import async_session_maker
from app.services.catalog import get_plan, list_plans
from app.services.discounts import (
    create_discount_code,
    delete_discount_code,
    get_discount_code,
    get_discount_code_by_name,
    list_discount_codes,
    normalize_discount_code,
    set_discount_active,
    update_discount_code,
)

router = Router(name="admin_discounts")
router.message.filter(IsSalesAdmin())
router.callback_query.filter(IsSalesAdmin())

_LIST_TEXT = "🏷 <b>Discount Codes</b>"
_NAME_PROMPT_TEXT = "Type the new discount code (letters/numbers, will be upper-cased):"
_DUPLICATE_CODE_TEXT = "⚠️ That code already exists. Type a different one:"
_PERCENT_PROMPT_TEXT = "Type the discount percent (0–100):"
_INVALID_PERCENT_TEXT = "⚠️ Send a number greater than 0 and up to 100."
_USAGE_LIMIT_PROMPT_TEXT = "Type a usage limit, or tap Unlimited:"
_INVALID_USAGE_LIMIT_TEXT = "⚠️ Send a positive whole number, or tap Unlimited."
_PLANS_PROMPT_TEXT = "Select which plans this code applies to:"
_NEED_ONE_PLAN_TEXT = "⚠️ Select at least one plan before continuing."
_VISIBILITY_PROMPT_TEXT = "Should this code be public (auto-applied) or private (typed only)?"


async def _scope_text(session: AsyncSession, discount: DiscountCode) -> str:
    if discount.plan_ids is None:
        return "All plans"
    names = []
    for pid in (int(x) for x in discount.plan_ids.split(",")):
        plan = await get_plan(session, pid)
        names.append(plan.name if plan is not None else f"#{pid}")
    return ", ".join(names)


def _detail_text(discount: DiscountCode, scope: str) -> str:
    limit = "Unlimited" if discount.usage_limit is None else str(discount.usage_limit)
    status = "Active" if discount.is_active else "Inactive"
    visibility = "Public" if discount.is_public else "Private"
    return (
        f"🏷 <b>{html.escape(discount.code)}</b>\n"
        f"Discount: {discount.percent}%\n"
        f"Usage: {discount.used_count}/{limit}\n"
        f"Plans: {scope}\n"
        f"Status: {status} · {visibility}"
    )


async def _render_list() -> tuple[str, InlineKeyboardMarkup]:
    async with async_session_maker() as session:
        discounts = await list_discount_codes(session)
    return _LIST_TEXT, discount_list_keyboard(discounts)


def _usage_limit_hint(discount: DiscountCode) -> str:
    limit = "Unlimited" if discount.usage_limit is None else str(discount.usage_limit)
    return f"Current usage limit: {limit}"


def _visibility_hint(discount: DiscountCode) -> str:
    return f"Current visibility: {'Public' if discount.is_public else 'Private'}"


async def _prompt_with_edit_hint(state: FSMContext, prompt: str, hint_builder: Any) -> str:
    """Prepends a "Current X: ..." reminder line to a wizard prompt when
    the wizard is in edit mode (editing_id set), mirroring the hint
    discount_edit_cb already shows for the percent step - so every step
    an admin passes through while editing reflects the value they're
    about to overwrite, not just the first one."""
    data = await state.get_data()
    editing_id = data.get("editing_id")
    if editing_id is None:
        return prompt
    async with async_session_maker() as session:
        discount = await get_discount_code(session, editing_id)
    if discount is None:
        return prompt
    return f"{hint_builder(discount)}\n\n{prompt}"


@router.callback_query(F.data == "adm:discounts")
async def discounts_list_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, keyboard = await _render_list()
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:view:"))
async def discount_view_cb(callback: CallbackQuery) -> None:
    discount_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        discount = await get_discount_code(session, discount_id)
        if discount is None:
            text, keyboard = await _render_list()
        else:
            scope = await _scope_text(session, discount)
            text, keyboard = _detail_text(discount, scope), discount_detail_keyboard(discount)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:toggle:"))
async def discount_toggle_cb(callback: CallbackQuery) -> None:
    discount_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        current = await get_discount_code(session, discount_id)
        discount = await set_discount_active(session, discount_id, not current.is_active) if current is not None else None
        if discount is None:
            text, keyboard = await _render_list()
        else:
            scope = await _scope_text(session, discount)
            text, keyboard = _detail_text(discount, scope), discount_detail_keyboard(discount)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:delete:") & ~F.data.endswith(":confirm"))
async def discount_delete_prompt_cb(callback: CallbackQuery) -> None:
    discount_id = int(callback.data.split(":")[-1])
    if callback.message is not None:
        await callback.message.edit_text(
            "🗑 Delete this discount code? This can't be undone.",
            reply_markup=discount_delete_confirm_keyboard(discount_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:delete:") & F.data.endswith(":confirm"))
async def discount_delete_confirm_cb(callback: CallbackQuery) -> None:
    discount_id = int(callback.data.split(":")[-2])
    async with async_session_maker() as session:
        await delete_discount_code(session, discount_id)
    text, keyboard = await _render_list()
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("🗑 Deleted.")


@router.callback_query(F.data == "adm:discounts:new")
async def discount_new_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DiscountCodeStates.name)
    await state.update_data(editing_id=None)
    if callback.message is not None:
        await callback.message.edit_text(_NAME_PROMPT_TEXT, reply_markup=wizard_cancel_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:edit:"))
async def discount_edit_cb(callback: CallbackQuery, state: FSMContext) -> None:
    discount_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        discount = await get_discount_code(session, discount_id)
        if discount is None:
            text, keyboard = await _render_list()
            if callback.message is not None:
                await callback.message.edit_text(text, reply_markup=keyboard)
            await callback.answer()
            return
        active_plans = await list_plans(session, active_only=True)

    # Editing skips the name step (code text is immutable) and pre-fills
    # every other field, matching AloBot's editing_id-conditional flow.
    # plan_ids is None means "every plan" - pre-select every currently
    # active plan so the picker reflects that instead of showing nothing
    # checked (mirrors the symmetric "all selected -> plan_ids=None"
    # collapse in discount_wizard_finish_cb).
    selected_plan_ids = (
        [p.id for p in active_plans]
        if discount.plan_ids is None
        else [int(p) for p in discount.plan_ids.split(",")]
    )
    await state.set_state(DiscountCodeStates.percent)
    await state.update_data(editing_id=discount.id, code=discount.code, selected_plan_ids=selected_plan_ids)
    if callback.message is not None:
        await callback.message.edit_text(
            f"Current percent: {discount.percent}%\n\n{_PERCENT_PROMPT_TEXT}", reply_markup=wizard_cancel_keyboard()
        )
    await callback.answer()


@router.message(DiscountCodeStates.name)
async def discount_wizard_receive_name(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer(_NAME_PROMPT_TEXT, reply_markup=wizard_cancel_keyboard())
        return
    code = normalize_discount_code(raw)
    async with async_session_maker() as session:
        existing = await get_discount_code_by_name(session, code)
    if existing is not None:
        await message.answer(_DUPLICATE_CODE_TEXT, reply_markup=wizard_cancel_keyboard())
        return
    await state.update_data(code=code)
    await state.set_state(DiscountCodeStates.percent)
    await message.answer(_PERCENT_PROMPT_TEXT, reply_markup=wizard_cancel_keyboard())


@router.message(DiscountCodeStates.percent)
async def discount_wizard_receive_percent(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        percent = Decimal(raw)
    except InvalidOperation:
        await message.answer(_INVALID_PERCENT_TEXT, reply_markup=wizard_cancel_keyboard())
        return
    if not (Decimal("0") < percent <= Decimal("100")):
        await message.answer(_INVALID_PERCENT_TEXT, reply_markup=wizard_cancel_keyboard())
        return
    await state.update_data(percent=str(percent))
    await state.set_state(DiscountCodeStates.usage_limit)
    text = await _prompt_with_edit_hint(state, _USAGE_LIMIT_PROMPT_TEXT, _usage_limit_hint)
    await message.answer(text, reply_markup=wizard_usage_limit_keyboard())


async def _enter_plans_step(state: FSMContext) -> tuple[str, InlineKeyboardMarkup]:
    data = await state.get_data()
    await state.set_state(DiscountCodeStates.plans)
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    selected = data.get("selected_plan_ids", [])
    return _PLANS_PROMPT_TEXT, wizard_plans_keyboard(plans, selected)


@router.message(DiscountCodeStates.usage_limit)
async def discount_wizard_receive_usage_limit(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(_INVALID_USAGE_LIMIT_TEXT, reply_markup=wizard_usage_limit_keyboard())
        return
    await state.update_data(usage_limit=int(raw))
    text, keyboard = await _enter_plans_step(state)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(DiscountCodeStates.usage_limit, F.data == "adm:discounts:wizard:unlimited")
async def discount_wizard_unlimited_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(usage_limit=None)
    text, keyboard = await _enter_plans_step(state)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(DiscountCodeStates.plans, F.data.startswith("adm:discounts:wizard:plan:"))
async def discount_wizard_toggle_plan_cb(callback: CallbackQuery, state: FSMContext) -> None:
    plan_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    selected: list[int] = list(data.get("selected_plan_ids", []))
    if plan_id in selected:
        selected.remove(plan_id)
    else:
        selected.append(plan_id)
    await state.update_data(selected_plan_ids=selected)
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    if callback.message is not None:
        await callback.message.edit_text(_PLANS_PROMPT_TEXT, reply_markup=wizard_plans_keyboard(plans, selected))
    await callback.answer()


@router.callback_query(DiscountCodeStates.plans, F.data == "adm:discounts:wizard:allplans")
async def discount_wizard_toggle_all_plans_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    data = await state.get_data()
    selected = data.get("selected_plan_ids", [])
    new_selected: list[int] = [] if len(selected) == len(plans) else [p.id for p in plans]
    await state.update_data(selected_plan_ids=new_selected)
    if callback.message is not None:
        await callback.message.edit_text(_PLANS_PROMPT_TEXT, reply_markup=wizard_plans_keyboard(plans, new_selected))
    await callback.answer()


@router.callback_query(DiscountCodeStates.plans, F.data == "adm:discounts:wizard:plansdone")
async def discount_wizard_plans_done_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("selected_plan_ids"):
        await callback.answer(_NEED_ONE_PLAN_TEXT, show_alert=True)
        return
    await state.set_state(DiscountCodeStates.visibility)
    text = await _prompt_with_edit_hint(state, _VISIBILITY_PROMPT_TEXT, _visibility_hint)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=wizard_visibility_keyboard())
    await callback.answer()


@router.callback_query(
    DiscountCodeStates.visibility, F.data.in_({"adm:discounts:wizard:public", "adm:discounts:wizard:private"})
)
async def discount_wizard_finish_cb(callback: CallbackQuery, state: FSMContext) -> None:
    is_public = callback.data.endswith(":public")
    data = await state.get_data()
    editing_id = data.get("editing_id")

    async with async_session_maker() as session:
        all_plans = await list_plans(session, active_only=True)
        selected: list[int] = data["selected_plan_ids"]
        plan_ids = None if len(selected) == len(all_plans) else selected
        percent = Decimal(data["percent"])
        usage_limit = data.get("usage_limit")

        if editing_id is None:
            discount = await create_discount_code(
                session, code=data["code"], percent=percent, usage_limit=usage_limit,
                plan_ids=plan_ids, is_public=is_public,
            )
        else:
            discount = await update_discount_code(
                session, editing_id, percent=percent, usage_limit=usage_limit,
                plan_ids=plan_ids, is_public=is_public,
            )
        scope = await _scope_text(session, discount) if discount is not None else ""

    await state.clear()
    if discount is not None and callback.message is not None:
        await callback.message.edit_text(_detail_text(discount, scope), reply_markup=discount_detail_keyboard(discount))
    await callback.answer()
