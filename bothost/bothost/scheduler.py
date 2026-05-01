"""Background expiration job: stops bots whose subscription has run out."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bothost.db import Database
from bothost.runner import BotRunner

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
        notified: set[int] = set()
        now = datetime.now(UTC)
        for record in running:
            sub = await self._db.get_subscription(record.tg_id)
            if sub and sub.expires_at > now:
                continue
            logger.info(
                "subscription expired for user %s, stopping bot %s", record.tg_id, record.id
            )
            try:
                await self._runner.stop(record.container_name, remove=True)
            except Exception:  # pragma: no cover — best effort
                logger.exception("failed to stop expired bot %s", record.id)
            await self._db.update_bot_status(bot_id=record.id, status="expired")
            if record.tg_id not in notified:
                notified.add(record.tg_id)
                try:
                    await self._bot.send_message(
                        chat_id=record.tg_id,
                        text=(
                            "⏰ Подписка истекла — все ваши боты остановлены.\n"
                            "Купите подписку через /buy, чтобы запустить их снова."
                        ),
                    )
                except Exception:  # pragma: no cover
                    logger.warning("failed to notify user %s about expiration", record.tg_id)
