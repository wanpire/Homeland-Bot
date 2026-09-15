from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TutorialAdminStates(StatesGroup):
    """One flow, three targets (stored in FSM data as `target`:
    "guide" | "profile" | "link"), rather than one state class per
    target - each target needs the same pick-protocol -> pick-platform
    -> await-content shape, just landing in a different table/config key
    at the end."""

    pick_protocol = State()
    pick_platform = State()
    await_content = State()
