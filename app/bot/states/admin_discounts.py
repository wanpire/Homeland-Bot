from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class DiscountCodeStates(StatesGroup):
    name = State()
    percent = State()
    usage_limit = State()
    plans = State()
    visibility = State()
