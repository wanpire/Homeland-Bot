from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CampaignStates(StatesGroup):
    content = State()
    button_choice = State()
    custom_label = State()
    custom_dest = State()
    custom_url = State()
    confirm = State()
