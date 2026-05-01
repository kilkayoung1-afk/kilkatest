"""Admin-only commands."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bothost.config import Config
from bothost.db import Database
from bothost.runner import BotRunner

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _is_admin(message: Message, cfg: Config) -> bool:
    if message.from_user is None:
        return False
    return cfg.is_admin(message.from_user.id)


@router.message(Command("stats"))
async def cmd_stats(message: Message, cfg: Config, db: Database, runner: BotRunner) -> None:
    if not _is_admin(message, cfg):
        return
    users = await db.count_users()
    active = await db.list_active_subscriptions()
    earned = await db.total_paid_stars()
    running_count = 0
    for sub in active:
        if await runner.is_running(sub.tg_id):
            running_count += 1
    await message.answer(
        "📊 <b>Статистика</b>\n"
        f"👥 Пользователей: {users}\n"
        f"💳 Активных подписок: {len(active)}\n"
        f"🤖 Запущенных ботов: {running_count}\n"
        f"⭐ Всего заработано: {earned}"
    )


@router.message(Command("users"))
async def cmd_users(message: Message, cfg: Config, db: Database) -> None:
    if not _is_admin(message, cfg):
        return
    active = await db.list_active_subscriptions()
    if not active:
        await message.answer("Нет активных подписок.")
        return
    lines = ["📋 <b>Активные подписки</b>"]
    for sub in active[:50]:
        lines.append(
            f"• <code>{sub.tg_id}</code> до "
            f"{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')} ({sub.paid_stars}⭐)"
        )
    if len(active) > 50:
        lines.append(f"…и ещё {len(active) - 50}")
    await message.answer("\n".join(lines))


@router.message(Command("extend"))
async def cmd_extend(message: Message, command: CommandObject, cfg: Config, db: Database) -> None:
    if not _is_admin(message, cfg):
        return
    if not command.args:
        await message.answer("Использование: /extend &lt;tg_id&gt; &lt;дни&gt;")
        return
    parts = command.args.split()
    if len(parts) != 2:
        await message.answer("Использование: /extend &lt;tg_id&gt; &lt;дни&gt;")
        return
    try:
        target_id = int(parts[0])
        days = int(parts[1])
    except ValueError:
        await message.answer("tg_id и days должны быть числами.")
        return
    await db.upsert_user(target_id, None)
    sub = await db.extend_subscription(target_id, days)
    await message.answer(
        f"✅ Подписка пользователя <code>{target_id}</code> продлена.\n"
        f"Активна до <b>{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>."
    )


@router.message(Command("admin_stop"))
async def cmd_admin_stop(
    message: Message,
    command: CommandObject,
    cfg: Config,
    db: Database,
    runner: BotRunner,
) -> None:
    if not _is_admin(message, cfg):
        return
    if not command.args:
        await message.answer("Использование: /admin_stop &lt;tg_id&gt;")
        return
    try:
        target_id = int(command.args.strip())
    except ValueError:
        await message.answer("tg_id должен быть числом.")
        return
    existed = await runner.stop(target_id, remove=True)
    record = await db.get_bot(target_id)
    if record is not None:
        await db.upsert_bot(
            tg_id=target_id,
            file_path=record.file_path,
            status="stopped",
            container_id=None,
        )
    await message.answer(
        "🛑 Бот пользователя остановлен." if existed else "У пользователя нет запущенного бота."
    )
