from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EditSupportStates(StatesGroup):
    support_username = State()


class EditMandatoryChannelStates(StatesGroup):
    channels = State()


class EditReminderStates(StatesGroup):
    days_before = State()


class EditPlanPriceStates(StatesGroup):
    price = State()


class EditCryptoSettlementStates(StatesGroup):
    """Network is chosen via inline buttons (a small fixed set), stored
    in FSM data by the handler that sets this state - only the address
    itself needs a text-input state."""
    address = State()
