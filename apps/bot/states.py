from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class NewsDraft(StatesGroup):
    """News-by-forward publishing flow."""
    waiting_title = State()
    waiting_server = State()
    waiting_category = State()
    waiting_targets = State()
