from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EditSalesMessageStates(StatesGroup):
    #: The language being edited travels in the FSM data as "lang".
    text = State()
