"""FSM-состояния родительского бота."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddBot(StatesGroup):
    waiting_token = State()


class EditStartMessage(StatesGroup):
    waiting_text = State()


class AddCommand(StatesGroup):
    waiting_command = State()
    waiting_response = State()


class AddTrigger(StatesGroup):
    waiting_pattern = State()
    waiting_response = State()


class AddKeyboard(StatesGroup):
    waiting_kind = State()
    waiting_title = State()


class AddButton(StatesGroup):
    waiting_text = State()
    waiting_emoji = State()
    waiting_action = State()
    waiting_payload = State()


class Broadcast(StatesGroup):
    waiting_message = State()
    confirm = State()


class SubscribeGate(StatesGroup):
    waiting_channel = State()
    waiting_link = State()
