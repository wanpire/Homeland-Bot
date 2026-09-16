from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BlockUserStates(StatesGroup):
    telegram_id = State()
