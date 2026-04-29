"""Главное меню и общие клавиатуры родительского бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from telegram_bot_constructor.db.models import ChildBot
from telegram_bot_constructor.emoji import (
    E_BOT,
    E_CHECK,
    E_CROSS,
    E_DOWNLOAD,
    E_INFO,
    E_LOCK_CLOSED,
    E_LOCK_OPEN,
    E_MEGAPHONE,
    E_PENCIL,
    E_PEOPLE,
    E_SETTINGS,
    E_STATS,
    E_TRASH,
)
from telegram_bot_constructor.keyboards import inline_button, inline_kb


def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню (после ``/start``)."""
    return inline_kb([
        [inline_button("Мои боты", callback_data="my_bots", icon=E_BOT)],
        [inline_button("Добавить бота", callback_data="add_bot", icon=E_SETTINGS)],
        [inline_button("Помощь", callback_data="help", icon=E_INFO)],
    ])


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return inline_kb([
        [inline_button("Назад в меню", callback_data="menu", icon=E_SETTINGS)],
    ])


def my_bots_kb(bots: list[ChildBot]) -> InlineKeyboardMarkup:
    rows = []
    for b in bots:
        title = b.title or b.username or f"bot:{b.bot_tg_id}"
        icon = E_CHECK if b.is_active else E_CROSS
        rows.append([
            inline_button(f"{title}", callback_data=f"bot:{b.id}", icon=icon)
        ])
    rows.append([
        inline_button("Добавить бота", callback_data="add_bot", icon=E_SETTINGS)
    ])
    rows.append([
        inline_button("Назад в меню", callback_data="menu", icon=E_SETTINGS)
    ])
    return inline_kb(rows)


def bot_card_kb(bot: ChildBot) -> InlineKeyboardMarkup:
    """Меню управления конкретным дочерним ботом."""
    toggle_text = "Выключить" if bot.is_active else "Включить"
    toggle_icon = E_LOCK_CLOSED if bot.is_active else E_LOCK_OPEN
    return inline_kb([
        [
            inline_button(
                "Сообщение /start", callback_data=f"bot:{bot.id}:start", icon=E_PENCIL
            ),
        ],
        [
            inline_button(
                "Команды", callback_data=f"bot:{bot.id}:cmds", icon=E_SETTINGS
            ),
            inline_button(
                "Триггеры", callback_data=f"bot:{bot.id}:trig", icon=E_MEGAPHONE
            ),
        ],
        [
            inline_button(
                "Клавиатуры", callback_data=f"bot:{bot.id}:kbs", icon=E_SETTINGS
            ),
        ],
        [
            inline_button(
                "Подписка-гейт", callback_data=f"bot:{bot.id}:sub", icon=E_LOCK_CLOSED
            ),
        ],
        [
            inline_button(
                "Рассылка", callback_data=f"bot:{bot.id}:cast", icon=E_MEGAPHONE
            ),
            inline_button(
                "Статистика", callback_data=f"bot:{bot.id}:stat", icon=E_STATS
            ),
        ],
        [
            inline_button(
                "Пользователи", callback_data=f"bot:{bot.id}:users", icon=E_PEOPLE
            ),
        ],
        [
            inline_button(
                "Выгрузить код", callback_data=f"bot:{bot.id}:export", icon=E_DOWNLOAD
            ),
        ],
        [
            inline_button(toggle_text, callback_data=f"bot:{bot.id}:toggle", icon=toggle_icon),
            inline_button("Удалить", callback_data=f"bot:{bot.id}:del", icon=E_TRASH),
        ],
        [
            inline_button("Мои боты", callback_data="my_bots", icon=E_BOT),
        ],
    ])
