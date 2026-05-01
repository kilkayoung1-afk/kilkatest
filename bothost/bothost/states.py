"""FSM states for multi-step interactions."""

from aiogram.fsm.state import State, StatesGroup


class UploadBot(StatesGroup):
    waiting_for_name = State()
    waiting_for_replace_confirmation = State()


class RenameBot(StatesGroup):
    waiting_for_name = State()
