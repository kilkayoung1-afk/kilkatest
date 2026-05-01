"""User-facing commands to manage their own bot."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bothost.db import Database
from bothost.runner import BotRunner

logger = logging.getLogger(__name__)
router = Router(name="manage")


async def _status(message: Message, db: Database, runner: BotRunner, tg_id: int) -> None:
    sub = await db.active_subscription(tg_id)
    bot_record = await db.get_bot(tg_id)

    parts: list[str] = []
    if sub:
        parts.append(
            f"📅 Подписка активна до <b>{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>"
        )
    else:
        parts.append("📅 Подписка не активна. Купи её через /buy.")

    if bot_record is None:
        parts.append("🤖 Бот ещё не загружен. Пришли .py файл, чтобы запустить.")
    else:
        running = await runner.is_running(tg_id)
        status = "🟢 запущен" if running else f"⚪ {bot_record.status}"
        parts.append(f"🤖 Бот: {status}")
        if bot_record.last_error:
            parts.append(f"⚠️ Последняя ошибка: <code>{bot_record.last_error[:200]}</code>")

    await message.answer("\n".join(parts))


async def _stop(message: Message, db: Database, runner: BotRunner, tg_id: int) -> None:
    record = await db.get_bot(tg_id)
    if record is None:
        await message.answer("Нет загруженного бота.")
        return
    existed = await runner.stop(tg_id, remove=True)
    await db.upsert_bot(
        tg_id=tg_id,
        file_path=record.file_path,
        status="stopped",
        container_id=None,
    )
    await message.answer("🛑 Бот остановлен." if existed else "Бот уже не работал.")


async def _restart(message: Message, db: Database, runner: BotRunner, tg_id: int) -> None:
    sub = await db.active_subscription(tg_id)
    if sub is None:
        await message.answer("❌ Нет активной подписки. Купи через /buy.")
        return
    record = await db.get_bot(tg_id)
    if record is None:
        await message.answer("❌ Нет загруженного бота. Пришли .py файл.")
        return
    progress = await message.answer("🔄 Перезапускаю…")
    try:
        container_id = await runner.start(tg_id)
    except Exception as exc:  # noqa: BLE001 — surface error to user
        logger.exception("restart failed for %s", tg_id)
        await db.upsert_bot(
            tg_id=tg_id,
            file_path=record.file_path,
            status="crashed",
            last_error=str(exc),
        )
        await progress.edit_text(f"❌ Не удалось перезапустить: <code>{exc}</code>")
        return
    await db.upsert_bot(
        tg_id=tg_id,
        file_path=record.file_path,
        status="running",
        container_id=container_id,
    )
    await progress.edit_text("✅ Бот перезапущен.")


async def _logs(message: Message, runner: BotRunner, tg_id: int) -> None:
    text = await runner.logs(tg_id, tail=50)
    if not text.strip():
        await message.answer("Логи пустые.")
        return
    truncated = text[-3500:]
    await message.answer(f"📜 <pre>{truncated}</pre>")


@router.message(Command("mybot"))
async def cmd_mybot(message: Message, db: Database, runner: BotRunner) -> None:
    if message.from_user is None:
        return
    await _status(message, db, runner, message.from_user.id)


@router.message(Command("stop"))
async def cmd_stop(message: Message, db: Database, runner: BotRunner) -> None:
    if message.from_user is None:
        return
    await _stop(message, db, runner, message.from_user.id)


@router.message(Command("restart"))
async def cmd_restart(message: Message, db: Database, runner: BotRunner) -> None:
    if message.from_user is None:
        return
    await _restart(message, db, runner, message.from_user.id)


@router.message(Command("logs"))
async def cmd_logs(message: Message, runner: BotRunner) -> None:
    if message.from_user is None:
        return
    await _logs(message, runner, message.from_user.id)


@router.callback_query(F.data == "mybot")
async def cb_mybot(call: CallbackQuery, db: Database, runner: BotRunner) -> None:
    if call.from_user is not None and isinstance(call.message, Message):
        await _status(call.message, db, runner, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "stop")
async def cb_stop(call: CallbackQuery, db: Database, runner: BotRunner) -> None:
    if call.from_user is not None and isinstance(call.message, Message):
        await _stop(call.message, db, runner, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "restart")
async def cb_restart(call: CallbackQuery, db: Database, runner: BotRunner) -> None:
    if call.from_user is not None and isinstance(call.message, Message):
        await _restart(call.message, db, runner, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "logs")
async def cb_logs(call: CallbackQuery, runner: BotRunner) -> None:
    if call.from_user is not None and isinstance(call.message, Message):
        await _logs(call.message, runner, call.from_user.id)
    await call.answer()
