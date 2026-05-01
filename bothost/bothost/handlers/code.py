"""Receive a .py file from the user and start it as a bot."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from bothost.config import Config
from bothost.db import Database
from bothost.runner import BotRunner
from bothost.validator import validate_user_script

logger = logging.getLogger(__name__)
router = Router(name="code")


@router.callback_query(F.data == "upload")
async def cb_upload(call: CallbackQuery) -> None:
    if isinstance(call.message, Message):
        await call.message.answer("📤 Пришли мне .py файл со своим ботом одним сообщением.")
    await call.answer()


@router.message(F.document)
async def handle_document(
    message: Message,
    bot: Bot,
    cfg: Config,
    db: Database,
    runner: BotRunner,
) -> None:
    if message.from_user is None or message.document is None:
        return
    user = message.from_user

    await db.upsert_user(user.id, user.username)

    sub = await db.active_subscription(user.id)
    if sub is None:
        await message.answer(
            "❌ Нет активной подписки.\n"
            f"Купи её за <b>{cfg.subscription_stars}⭐</b> командой /buy и пришли файл снова."
        )
        return

    file_name = message.document.file_name or ""
    if not file_name.lower().endswith(".py"):
        await message.answer("❌ Принимаются только файлы с расширением <code>.py</code>.")
        return

    file = await bot.get_file(message.document.file_id)
    if file.file_path is None:
        await message.answer("❌ Не удалось скачать файл, попробуй ещё раз.")
        return

    buf = await bot.download_file(file.file_path)
    if buf is None:
        await message.answer("❌ Не удалось скачать файл, попробуй ещё раз.")
        return
    source = buf.read()

    result = validate_user_script(source)
    if not result.ok:
        await message.answer(f"❌ {result.error}")
        return

    notice = "🚀 Запускаю бота…"
    if result.warnings:
        warn_text = "\n".join(f"⚠️ {w}" for w in result.warnings)
        notice = f"{warn_text}\n\n{notice}"

    progress = await message.answer(notice)

    path = await runner.save_script(user.id, source)
    await db.upsert_bot(
        tg_id=user.id,
        file_path=str(path),
        status="stopped",
    )

    try:
        container_id = await runner.start(user.id)
    except Exception as exc:  # noqa: BLE001 — surface error to the user
        logger.exception("failed to start bot for user %s", user.id)
        await db.upsert_bot(
            tg_id=user.id,
            file_path=str(path),
            status="crashed",
            last_error=str(exc),
        )
        await progress.edit_text(
            f"❌ Не удалось запустить бота: <code>{exc}</code>\nПроверь код и пришли файл снова."
        )
        return

    await db.upsert_bot(
        tg_id=user.id,
        file_path=str(path),
        status="running",
        container_id=container_id,
    )
    await progress.edit_text(
        "✅ Бот запущен!\n"
        f"Подписка активна до <b>{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>.\n\n"
        "Команды управления: /mybot /restart /stop /logs"
    )


@router.message(F.text & ~F.text.startswith("/"))
async def reject_text(message: Message) -> None:
    """Friendly reminder if the user pastes raw text instead of a .py file."""
    await message.answer(
        "📎 Пришли код одним <b>.py файлом</b>, а не текстом — так я смогу его запустить."
    )
