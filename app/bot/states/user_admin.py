from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class UserLookupStates(StatesGroup):
    #: Held only while an admin types an id or username; cleared as soon
    #: as it resolves, so no lookup state outlives one search.
    query = State()
