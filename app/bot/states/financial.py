from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class PaymentSearchStates(StatesGroup):
    #: Only held while the admin is typing a username or id; the result
    #: is folded straight into callback data, so no filter state ever
    #: lives in FSM.
    query = State()
