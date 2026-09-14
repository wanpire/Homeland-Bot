from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.handlers.users import send_main_menu

router = Router(name="fallback")


@router.message()
async def fallback_to_main_menu(message: Message, state: FSMContext) -> None:
    """Registered last in main.py, after every other router - only ever
    reached once no command/state-specific handler claimed the message
    first. Shows the main menu unless the user has an FSM state in
    progress, in which case some state-specific handler already had
    first refusal and this isn't the place to guess at what they meant."""
    if await state.get_state() is not None:
        return
    await send_main_menu(message)
