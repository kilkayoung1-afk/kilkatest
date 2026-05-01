"""Process entrypoint: wire up dispatcher, start polling and the expiration job."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bothost.config import Config
from bothost.db import Database
from bothost.handlers import register
from bothost.runner import BotRunner
from bothost.scheduler import ExpirationService

logger = logging.getLogger(__name__)


PUBLIC_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="buy", description="Купить подписку"),
    BotCommand(command="bots", description="Мои боты"),
    BotCommand(command="status", description="Статус подписки"),
    BotCommand(command="help", description="Помощь"),
    BotCommand(command="terms", description="Условия использования"),
    BotCommand(command="privacy", description="Конфиденциальность"),
]


async def _run() -> None:
    cfg = Config.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    db = Database(cfg.db_path)
    await db.init()

    runner = BotRunner(cfg)
    bot = Bot(
        token=cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp["cfg"] = cfg
    dp["db"] = db
    dp["runner"] = runner
    register(dp)

    expiration = ExpirationService(db=db, runner=runner, bot=bot)
    expiration.start()

    me = await bot.get_me()
    logger.info("starting parent bot @%s (id=%s)", me.username, me.id)
    try:
        await bot.set_my_commands(PUBLIC_COMMANDS)
    except Exception as exc:  # pragma: no cover - non-critical
        logger.warning("set_my_commands failed: %s", exc)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await expiration.shutdown()
        await bot.session.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
