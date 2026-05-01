"""Background expiration job: stops bots whose subscription has run out."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .db import Database
from .runner import BotRunner

logger = logging.getLogger(__name__)


class ExpirationService:
    def __init__(self, db: Database, runner: BotRunner, bot: Bot):
        self._db = db
        self._runner = runner
        self._bot = bot
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        self._scheduler.add_job(
            self.tick,
            trigger="interval",
            minutes=1,
            id="bothost-expiration",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.start()

    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    async def tick(self) -> None:
        running = await self._db.list_running_bots()
        if not running:
            return
        for record in running:
            sub = await self._db.active_subscription(record.tg_id)
            if sub and sub.expires_at > datetime.now(UTC):
                continue
            logger.info("subscription expired for user %s, stopping bot", record.tg_id)
            try:
                await self._runner.stop(record.tg_id, remove=True)
            except Exception:  # pragma: no cover - container ops are best-effort
                logger.exception("failed to stop expired bot for user %s", record.tg_id)
            await self._db.upsert_bot(
                tg_id=record.tg_id,
                file_path=record.file_path,
                status="expired",
                container_id=None,
            )
            try:
                await self._bot.send_message(
                    chat_id=record.tg_id,
                    text=(
                        "⏰ Подписка истекла — твой бот остановлен.\n"
                        "Продли её командой /buy, чтобы запустить снова."
                    ),
                )
            except Exception:  # pragma: no cover — user might have blocked the bot
                logger.warning("failed to notify user %s about expiration", record.tg_id)
