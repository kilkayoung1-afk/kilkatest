"""Точка входа: запуск родительского бота и пула дочерних."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from telegram_bot_constructor.child.runtime import runtime
from telegram_bot_constructor.config import Settings
from telegram_bot_constructor.db.session import create_all, init_engine
from telegram_bot_constructor.parent.dispatcher import build_dispatcher

logger = logging.getLogger(__name__)


async def amain() -> None:
    settings = Settings.load()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting telegram-bot-constructor (admins=%s)", settings.admin_ids)

    init_engine(settings.database_url)
    await create_all()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()
    dp["settings"] = settings

    # Запустим всех активных дочерних ботов
    await runtime.start_all()

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Stop signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows
            pass

    polling_task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False),
        name="parent-polling",
    )

    try:
        # Ждём либо завершения родительского polling, либо stop_event
        wait_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {polling_task, wait_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
    finally:
        await runtime.stop_all()
        try:
            await bot.session.close()
        except Exception:
            pass
        logger.info("Bye")


def main() -> None:
    try:
        asyncio.run(amain())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
