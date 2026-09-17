from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddAdminStates(StatesGroup):
    telegram_id = State()
    level = State()
