"""Bot list, per-bot actions: start/stop/restart/logs/rename/replace/delete."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bothost import emoji as e
from bothost.config import Config
from bothost.db import BotRecord, Database, Subscription
from bothost.keyboards import (
    KBD_BOTS,
    bot_actions_menu,
    bots_list_menu,
    cancel_keyboard,
    confirm_delete,
    reply_keyboard,
)
from bothost.runner import BotRunner, slug_name
from bothost.states import RenameBot

logger = logging.getLogger(__name__)
router = Router(name="manage")


async def _sync_bot_to_sub(db: Database, record: BotRecord, sub: Subscription) -> BotRecord:
    """Pick max(bot, sub) for each resource so an upgraded sub takes effect on next start."""
    new_mem = max(record.mem_mb, sub.mem_mb)
    new_cpu = max(record.cpu_quota, sub.cpu_quota)
    new_disk = max(record.disk_mb, sub.disk_mb)
    new_fsize = max(record.fsize_mb, sub.fsize_mb)
    if (
        new_mem == record.mem_mb
        and new_cpu == record.cpu_quota
        and new_disk == record.disk_mb
        and new_fsize == record.fsize_mb
    ):
        return record
    await db.update_bot_resources(
        bot_id=record.id,
        plan_id=sub.plan_id or record.plan_id,
        mem_mb=new_mem,
        cpu_quota=new_cpu,
        disk_mb=new_disk,
        fsize_mb=new_fsize,
    )
    fresh = await db.get_bot_by_id(record.id)
    return fresh or record


async def _show_bots_list(target: Message, *, cfg: Config, db: Database, tg_id: int) -> None:
    bots = await db.list_bots_for_user(tg_id)
    sub = await db.get_subscription(tg_id)
    if not bots:
        await target.answer(
            f"{e.BOT} У вас пока нет ботов. Нажмите «Загрузить» снизу, чтобы добавить.",
            reply_markup=reply_keyboard(),
        )
        return
    header = _bots_header(sub, len(bots))
    await target.answer(header, reply_markup=bots_list_menu(bots))


def _bots_header(sub: Subscription | None, count: int) -> str:
    if sub and sub.is_active():
        return (
            f"{e.BOT} <b>Ваши боты</b> ({count}/{sub.bot_quota})\n"
            f"{e.CALENDAR} Активна до {sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"{e.TAG} Лимиты бота: {_resources_text(sub.mem_mb, sub.cpu_quota, sub.disk_mb)}"
        )
    return f"{e.BOT} <b>Ваши боты</b> ({count}). {e.CROSS} Подписка не активна."


def _resources_text(mem_mb: int, cpu_quota: float, disk_mb: int) -> str:
    def _fmt_mem(mb: int) -> str:
        if mb >= 1024 and mb % 1024 == 0:
            return f"{mb // 1024} ГБ"
        if mb >= 1024:
            return f"{mb / 1024:.1f} ГБ"
        return f"{mb} МБ"

    return f"{_fmt_mem(mem_mb)} RAM · {cpu_quota:g} CPU · {_fmt_mem(disk_mb)} диск"


async def _show_single_bot(
    target: Message,
    *,
    db: Database,
    runner: BotRunner,
    record: BotRecord,
) -> None:
    is_running = record.status == "running" and await runner.is_running(record.container_name)
    if is_running and record.status != "running":
        await db.update_bot_status(bot_id=record.id, status="running")
    if not is_running and record.status == "running":
        await db.update_bot_status(bot_id=record.id, status="crashed")
        record = (await db.get_bot_by_id(record.id)) or record
    lines = [
        f"{e.BOT} <b>{record.name}</b>",
        f"Статус: {record.status}",
        f"Создан: {record.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"{e.TAG} Лимиты: {_resources_text(record.mem_mb, record.cpu_quota, record.disk_mb)}",
    ]
    if record.last_error:
        lines.append(f"{e.CROSS} Последняя ошибка:")
        lines.append(f"<code>{record.last_error[:300]}</code>")
    await target.answer(
        "\n".join(lines), reply_markup=bot_actions_menu(record, is_running=is_running)
    )


@router.message(F.text == KBD_BOTS)
async def kbd_bots(message: Message, cfg: Config, db: Database, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    await _show_bots_list(message, cfg=cfg, db=db, tg_id=message.from_user.id)


@router.callback_query(F.data == "bots")
async def cb_bots(call: CallbackQuery, cfg: Config, db: Database) -> None:
    if call.from_user is None or not isinstance(call.message, Message):
        await call.answer()
        return
    await _show_bots_list(call.message, cfg=cfg, db=db, tg_id=call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("bot:"))
async def cb_bot_detail(call: CallbackQuery, db: Database, runner: BotRunner) -> None:
    if call.data is None or call.from_user is None or not isinstance(call.message, Message):
        await call.answer()
        return
    bot_id = int(call.data.split(":", 1)[1])
    record = await db.get_bot_by_id(bot_id)
    if record is None or record.tg_id != call.from_user.id:
        await call.answer("Не найден", show_alert=True)
        return
    await _show_single_bot(call.message, db=db, runner=runner, record=record)
    await call.answer()


@router.callback_query(F.data.startswith("act:"))
async def cb_bot_action(
    call: CallbackQuery,
    cfg: Config,
    db: Database,
    runner: BotRunner,
    state: FSMContext,
) -> None:
    if call.data is None or call.from_user is None or not isinstance(call.message, Message):
        await call.answer()
        return
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        await call.answer()
        return
    _, action, bot_id_str = parts
    bot_id = int(bot_id_str)
    record = await db.get_bot_by_id(bot_id)
    if record is None or record.tg_id != call.from_user.id:
        await call.answer("Не найден", show_alert=True)
        return

    if action == "start":
        sub = await db.get_subscription(call.from_user.id)
        if sub is None or not sub.is_active():
            await call.answer("⚠️ Подписка не активна", show_alert=True)
            return
        record = await _sync_bot_to_sub(db, record, sub)
        try:
            cid = await runner.start(
                tg_id=record.tg_id,
                bot_id=record.id,
                container_name=record.container_name,
                mem_mb=record.mem_mb,
                cpu_quota=record.cpu_quota,
                fsize_mb=record.fsize_mb,
            )
        except Exception as exc:
            logger.exception("start failed for bot %s", record.id)
            await db.update_bot_status(bot_id=record.id, status="crashed", last_error=str(exc))
            await call.message.answer(f"❌ Не удалось запустить:\n<code>{exc}</code>")
            await call.answer()
            return
        await db.update_bot_status(bot_id=record.id, status="running", container_id=cid)
        fresh = await db.get_bot_by_id(record.id)
        assert fresh is not None
        await call.message.answer(
            f"▶️ Бот <b>{fresh.name}</b> запущен.",
            reply_markup=bot_actions_menu(fresh, is_running=True),
        )
        await call.answer("Запущен")
        return

    if action == "stop":
        await runner.stop(record.container_name, remove=True)
        await db.update_bot_status(bot_id=record.id, status="stopped")
        fresh = await db.get_bot_by_id(record.id)
        assert fresh is not None
        await call.message.answer(
            f"⏹ Бот <b>{fresh.name}</b> остановлен.",
            reply_markup=bot_actions_menu(fresh, is_running=False),
        )
        await call.answer("Остановлен")
        return

    if action == "restart":
        sub = await db.get_subscription(call.from_user.id)
        if sub is None or not sub.is_active():
            await call.answer("⚠️ Подписка не активна", show_alert=True)
            return
        record = await _sync_bot_to_sub(db, record, sub)
        await runner.stop(record.container_name, remove=True)
        try:
            cid = await runner.start(
                tg_id=record.tg_id,
                bot_id=record.id,
                container_name=record.container_name,
                mem_mb=record.mem_mb,
                cpu_quota=record.cpu_quota,
                fsize_mb=record.fsize_mb,
            )
        except Exception as exc:
            logger.exception("restart failed for bot %s", record.id)
            await db.update_bot_status(bot_id=record.id, status="crashed", last_error=str(exc))
            await call.message.answer(f"❌ Не удалось перезапустить:\n<code>{exc}</code>")
            await call.answer()
            return
        await db.update_bot_status(bot_id=record.id, status="running", container_id=cid)
        fresh = await db.get_bot_by_id(record.id)
        assert fresh is not None
        await call.message.answer(
            f"🔄 Бот <b>{fresh.name}</b> перезапущен.",
            reply_markup=bot_actions_menu(fresh, is_running=True),
        )
        await call.answer("Перезапущен")
        return

    if action == "logs":
        text = await runner.logs(record.container_name, tail=50)
        text = (text or "пусто").strip()[-3500:]
        await call.message.answer(f"📜 <b>Логи {record.name}</b>:\n<pre>{_html_escape(text)}</pre>")
        await call.answer()
        return

    if action == "rename":
        await state.set_state(RenameBot.waiting_for_name)
        await state.update_data(rename_bot_id=record.id)
        await call.message.answer(
            f"✏️ Введи новое имя для <b>{record.name}</b>:",
            reply_markup=cancel_keyboard(),
        )
        await call.answer()
        return

    if action == "replace":
        await state.set_state(state=None)
        await state.update_data(replace_bot_id=record.id)
        await call.message.answer(
            f"🔁 Пришли новый <code>.py</code> или <code>.zip</code> для <b>{record.name}</b> — "
            "заменю код, переустановлю зависимости (если есть <code>requirements.txt</code>) "
            "и перезапущу.",
            reply_markup=cancel_keyboard(),
        )
        await call.answer()
        return

    if action == "delete":
        await call.message.answer(
            f"🗑 Точно удалить <b>{record.name}</b>?", reply_markup=confirm_delete(record.id)
        )
        await call.answer()
        return

    if action == "delete_confirm":
        await runner.stop(record.container_name, remove=True)
        await runner.cleanup_files(tg_id=record.tg_id, bot_id=record.id)
        await db.delete_bot(record.id)
        await call.message.answer(f"🗑 Бот <b>{record.name}</b> удалён.")
        await call.answer("Удалён")
        await _show_bots_list(call.message, cfg=cfg, db=db, tg_id=call.from_user.id)
        return

    await call.answer()


@router.message(RenameBot.waiting_for_name, F.text)
async def receive_new_name(
    message: Message,
    db: Database,
    runner: BotRunner,
    state: FSMContext,
) -> None:
    if message.from_user is None or message.text is None:
        return
    new_name = slug_name(message.text)
    if new_name is None:
        await message.answer(
            "❌ Имя должно быть из латинских букв/цифр/<code>_</code>/<code>-</code>, до 32 символов."
        )
        return
    data = await state.get_data()
    bot_id = data.get("rename_bot_id")
    if not isinstance(bot_id, int):
        await state.clear()
        return
    record = await db.get_bot_by_id(bot_id)
    if record is None or record.tg_id != message.from_user.id:
        await state.clear()
        return
    if await db.get_bot_by_name(message.from_user.id, new_name) is not None:
        await message.answer("❌ Имя уже занято.")
        return
    await db.rename_bot(bot_id=bot_id, new_name=new_name)
    await state.clear()
    fresh = await db.get_bot_by_id(bot_id)
    assert fresh is not None
    is_running = await runner.is_running(fresh.container_name)
    await message.answer(
        f"✏️ Переименован → <b>{fresh.name}</b>",
        reply_markup=bot_actions_menu(fresh, is_running=is_running),
    )


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
