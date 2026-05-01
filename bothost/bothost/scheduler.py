"""Background expiration job: stops bots whose subscription has run out.

Also enforces per-bot disk quota by sampling /app/data size every minute and
stopping bots that exceed their plan's disk limit.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bothost.config import Config
from bothost.db import Database
from bothost.runner import BotRunner

logger = logging.getLogger(__name__)


class ExpirationService:
    def __init__(self, db: Database, runner: BotRunner, bot: Bot, cfg: Config):
        self._db = db
        self._runner = runner
        self._bot = bot
        self._cfg = cfg
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
        self._scheduler.add_job(
            self.check_disk_quotas,
            trigger="interval",
            minutes=1,
            id="bothost-disk-quota",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.start()

    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    async def check_disk_quotas(self) -> None:
        """Stop any running bot whose /app/data exceeds its plan's disk_mb."""
        running = await self._db.list_running_bots()
        for record in running:
            limit_mb = record.disk_mb or 0
            if limit_mb <= 0:
                continue
            data_dir = self._cfg.user_bots_dir / str(record.tg_id) / str(record.id) / "data"
            try:
                used_bytes = await asyncio.to_thread(_dir_size, data_dir)
            except OSError:
                continue
            limit_bytes = limit_mb * 1024 * 1024
            if used_bytes <= limit_bytes:
                continue
            logger.info(
                "disk quota exceeded for bot %s (used=%dB limit=%dB), stopping",
                record.id,
                used_bytes,
                limit_bytes,
            )
            try:
                await self._runner.stop(record.container_name, remove=True)
            except Exception:
                logger.exception("failed to stop bot %s on quota overflow", record.id)
            await self._db.update_bot_status(
                bot_id=record.id,
                status="crashed",
                last_error=(
                    f"disk quota exceeded: used "
                    f"{used_bytes // (1024 * 1024)} MB > limit {limit_mb} MB"
                ),
            )
            try:
                await self._bot.send_message(
                    chat_id=record.tg_id,
                    text=(
                        f"⚠️ Бот <b>{record.name}</b> остановлен: превышен лимит диска "
                        f"({used_bytes // (1024 * 1024)} МБ / {limit_mb} МБ).\n"
                        "Удали лишние файлы в <code>/app/data</code> или возьми тариф побольше."
                    ),
                )
            except Exception:
                logger.warning("failed to notify user %s about disk overflow", record.tg_id)

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


def _dir_size(path: Path) -> int:
    """Return total bytes used under `path`. Symlinks are not followed."""
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            total += entry.stat().st_size
        except OSError:
            continue
    return total
