"""Inline keyboards used across the parent bot."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(*, has_active_sub: bool, has_bot: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_active_sub:
        rows.append(
            [
                InlineKeyboardButton(text="📤 Загрузить код", callback_data="upload"),
                InlineKeyboardButton(text="📊 Мой бот", callback_data="mybot"),
            ]
        )
        if has_bot:
            rows.append(
                [
                    InlineKeyboardButton(text="🔄 Перезапустить", callback_data="restart"),
                    InlineKeyboardButton(text="🛑 Остановить", callback_data="stop"),
                ]
            )
            rows.append([InlineKeyboardButton(text="📜 Логи", callback_data="logs")])
        rows.append([InlineKeyboardButton(text="➕ Продлить подписку", callback_data="buy")])
    else:
        rows.append(
            [InlineKeyboardButton(text="⭐ Купить подписку (50★ / 7 дней)", callback_data="buy")]
        )
    rows.append([InlineKeyboardButton(text="❓ Помощь", callback_data="help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
