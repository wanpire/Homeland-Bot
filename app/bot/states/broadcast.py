from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BroadcastStates(StatesGroup):
    content = State()
    confirm = State()
