"""Сборка диспетчера родительского бота с подключением всех роутеров."""

from __future__ import annotations

from aiogram import Dispatcher

from telegram_bot_constructor.parent.handlers import (
    admin,
    bots,
    broadcast,
    editor,
    keyboards,
    start,
    stats,
)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(bots.router)
    dp.include_router(editor.router)
    dp.include_router(keyboards.router)
    dp.include_router(broadcast.router)
    dp.include_router(stats.router)
    dp.include_router(admin.router)
    return dp
