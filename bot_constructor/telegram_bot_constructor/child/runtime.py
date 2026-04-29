"""Менеджер дочерних ботов: запускает polling в одном процессе для каждого.

Используется ``asyncio.create_task(dispatcher.start_polling(bot))`` на каждый
активный дочерний бот. При остановке закрываем сессию и отменяем задачу.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from telegram_bot_constructor.child.handlers import make_router
from telegram_bot_constructor.db.repo import get_all_active_bots, get_bot_by_id
from telegram_bot_constructor.db.session import session_scope

logger = logging.getLogger(__name__)


class ChildBotRuntime:
    """Управление пулом дочерних ботов."""

    def __init__(self) -> None:
        self._bots: dict[int, Bot] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._dispatchers: dict[int, Dispatcher] = {}
        self._lock = asyncio.Lock()

    async def start_all(self) -> None:
        """Запускает всех активных ботов из БД."""
        async with session_scope() as session:
            children = await get_all_active_bots(session)
            tokens = [(c.id, c.token) for c in children]
        for bot_id, _token in tokens:
            await self.start_bot_by_id(bot_id)

    async def start_bot_by_id(self, bot_id: int) -> None:
        async with self._lock:
            if bot_id in self._bots:
                return
            async with session_scope() as session:
                child = await get_bot_by_id(session, bot_id)
                if child is None or not child.is_active:
                    return
                token = child.token

            bot = Bot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            dp = Dispatcher()
            dp.include_router(make_router(bot_id))

            self._bots[bot_id] = bot
            self._dispatchers[bot_id] = dp
            task = asyncio.create_task(self._run(bot_id, bot, dp), name=f"child-{bot_id}")
            self._tasks[bot_id] = task
            logger.info("Started child bot id=%s", bot_id)

    async def _run(self, bot_id: int, bot: Bot, dp: Dispatcher) -> None:
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, handle_signals=False)
        except asyncio.CancelledError:
            logger.info("Child bot %s polling cancelled", bot_id)
            raise
        except Exception as exc:
            logger.exception("Child bot %s crashed: %s", bot_id, exc)
        finally:
            try:
                await bot.session.close()
            except Exception:
                pass

    async def stop_bot(self, bot_id: int) -> None:
        async with self._lock:
            task = self._tasks.pop(bot_id, None)
            bot = self._bots.pop(bot_id, None)
            self._dispatchers.pop(bot_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass
        logger.info("Stopped child bot id=%s", bot_id)

    async def stop_all(self) -> None:
        ids = list(self._tasks.keys())
        await asyncio.gather(*(self.stop_bot(i) for i in ids))


runtime = ChildBotRuntime()
