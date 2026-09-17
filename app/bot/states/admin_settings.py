from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EditSupportStates(StatesGroup):
    support_username = State()


class EditMandatoryChannelStates(StatesGroup):
    channels = State()
