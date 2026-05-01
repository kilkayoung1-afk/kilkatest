"""Admin-only commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bothost.config import Config
from bothost.db import Database
from bothost.plans import find_plan
from bothost.runner import BotRunner

router = Router(name="admin")


def _is_admin(message: Message, cfg: Config) -> bool:
    return message.from_user is not None and cfg.is_admin(message.from_user.id)


@router.message(Command("stats"))
async def cmd_stats(message: Message, cfg: Config, db: Database, runner: BotRunner) -> None:
    if not _is_admin(message, cfg):
        return
    users = await db.count_users()
    subs = await db.list_active_subscriptions()
    running = await db.list_running_bots()
    actually_running = 0
    for r in running:
        if await runner.is_running(r.container_name):
            actually_running += 1
    paid = await db.total_paid_stars()
    await message.answer(
        f"📊 <b>Статистика</b>\n"
        f"Пользователей: {users}\n"
        f"Активных подписок: {len(subs)}\n"
        f"Запущенных ботов: {actually_running}\n"
        f"Получено звёзд: {paid}⭐"
    )


@router.message(Command("users"))
async def cmd_users(message: Message, cfg: Config, db: Database) -> None:
    if not _is_admin(message, cfg):
        return
    subs = await db.list_active_subscriptions()
    if not subs:
        await message.answer("Активных подписок нет.")
        return
    lines = ["👥 <b>Активные подписки</b>:"]
    for s in subs:
        lines.append(
            f"• <code>{s.tg_id}</code> — до {s.expires_at.strftime('%Y-%m-%d %H:%M')}, "
            f"квота {s.bot_quota}, оплачено {s.total_paid_stars}⭐"
        )
    await message.answer("\n".join(lines))


@router.message(Command("extend"))
async def cmd_extend(message: Message, command: CommandObject, cfg: Config, db: Database) -> None:
    if not _is_admin(message, cfg):
        return
    args = (command.args or "").split()
    if len(args) < 2:
        await message.answer("Использование: /extend &lt;tg_id&gt; &lt;дни&gt; [квота]")
        return
    try:
        target = int(args[0])
        days = int(args[1])
        bots = int(args[2]) if len(args) >= 3 else 1
    except ValueError:
        await message.answer("Неверные аргументы.")
        return
    existing = await db.get_subscription(target)
    keep_mem = existing.mem_mb if existing else 256
    keep_cpu = existing.cpu_quota if existing else 0.5
    keep_disk = existing.disk_mb if existing else 100
    keep_fsize = existing.fsize_mb if existing else 50
    sub = await db.apply_payment(
        tg_id=target,
        plan_id="admin-extend",
        paid_stars=0,
        days=days,
        bots=bots,
        mem_mb=keep_mem,
        cpu_quota=keep_cpu,
        disk_mb=keep_disk,
        fsize_mb=keep_fsize,
        payment_charge_id=None,
    )
    await message.answer(
        f"✅ Подписка <code>{target}</code> продлена на {days} дн.\n"
        f"Сейчас: до {sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}, квота {sub.bot_quota}."
    )


@router.message(Command("grant"))
async def cmd_grant(
    message: Message,
    command: CommandObject,
    cfg: Config,
    db: Database,
) -> None:
    """Grant any plan or arbitrary days/quota to any user (admin-only).

    Usage:
      /grant <tg_id> <plan_id>          — issue plan from config
      /grant <tg_id> <days>             — extend by N days, quota unchanged (or 1)
      /grant <tg_id> <days> <bot_quota> — extend by N days, set quota
    """
    if not _is_admin(message, cfg):
        return
    args = (command.args or "").split()
    if len(args) < 2:
        await message.answer(
            "Использование:\n"
            "<code>/grant &lt;tg_id&gt; &lt;plan_id&gt;</code> — тариф из конфига\n"
            "<code>/grant &lt;tg_id&gt; &lt;дни&gt; [квота]</code> — произвольно"
        )
        return
    try:
        target = int(args[0])
    except ValueError:
        await message.answer("Неверный tg_id.")
        return

    second = args[1]
    plan = find_plan(cfg.plans, second)
    existing = await db.get_subscription(target)
    if plan is not None:
        days = plan.days
        bots = plan.bots
        plan_id = f"admin-grant-{plan.id}"
        mem_mb = plan.mem_mb
        cpu_quota = plan.cpu_quota
        disk_mb = plan.disk_mb
        fsize_mb = plan.fsize_mb
        label = f"{plan.name} ({plan.short_resources()} на {plan.days} дн)"
    else:
        try:
            days = int(second)
        except ValueError:
            await message.answer(
                f"Не понял второй аргумент. Тарифы: "
                f"{', '.join(p.id for p in cfg.plans)}, или число дней."
            )
            return
        if days <= 0:
            await message.answer("Дней должно быть > 0.")
            return
        if len(args) >= 3:
            try:
                bots = int(args[2])
            except ValueError:
                await message.answer("Квота должна быть числом.")
                return
            if bots < 1:
                await message.answer("Квота должна быть >= 1.")
                return
        else:
            bots = existing.bot_quota if existing else 1
        plan_id = "admin-grant-custom"
        mem_mb = existing.mem_mb if existing else 256
        cpu_quota = existing.cpu_quota if existing else 0.5
        disk_mb = existing.disk_mb if existing else 100
        fsize_mb = existing.fsize_mb if existing else 50
        label = f"{days} дн, квота {bots}"

    await db.upsert_user(target, None)
    sub = await db.apply_payment(
        tg_id=target,
        plan_id=plan_id,
        paid_stars=0,
        days=days,
        bots=bots,
        mem_mb=mem_mb,
        cpu_quota=cpu_quota,
        disk_mb=disk_mb,
        fsize_mb=fsize_mb,
        payment_charge_id=None,
    )
    await message.answer(
        f"✅ Выдано <code>{target}</code>: {label}\n"
        f"Сейчас: до {sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}, квота {sub.bot_quota}."
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
    args = (command.args or "").split()
    if not args:
        await message.answer("Использование: /admin_stop &lt;tg_id|all&gt;")
        return
    if args[0] == "all":
        bots = await db.list_running_bots()
    else:
        try:
            tg_id = int(args[0])
        except ValueError:
            await message.answer("Неверный tg_id.")
            return
        bots = [r for r in await db.list_running_bots() if r.tg_id == tg_id]
    if not bots:
        await message.answer("Нет запущенных ботов под эти аргументы.")
        return
    for r in bots:
        await runner.stop(r.container_name, remove=True)
        await db.update_bot_status(bot_id=r.id, status="stopped")
    await message.answer(f"⏹ Остановлено: {len(bots)}")


@router.message(Command("expire_in"))
async def cmd_expire_in(
    message: Message,
    command: CommandObject,
    cfg: Config,
    db: Database,
) -> None:
    """Admin: force a user's subscription to expire in N seconds (for testing)."""
    if not _is_admin(message, cfg):
        return
    args = (command.args or "").split()
    if len(args) < 2:
        await message.answer("Использование: /expire_in &lt;tg_id&gt; &lt;секунд&gt;")
        return
    try:
        target = int(args[0])
        seconds = int(args[1])
    except ValueError:
        await message.answer("Неверные аргументы.")
        return
    new_expiry = datetime.now(UTC) + timedelta(seconds=seconds)
    import aiosqlite

    async with aiosqlite.connect(cfg.db_path) as conn:
        await conn.execute(
            "UPDATE subscriptions SET expires_at = ?, updated_at = ? WHERE tg_id = ?",
            (new_expiry.isoformat(), datetime.now(UTC).isoformat(), target),
        )
        await conn.commit()
    await message.answer(
        f"⏳ Подписка {target} истечёт в {new_expiry.strftime('%Y-%m-%d %H:%M:%S UTC')}."
    )
