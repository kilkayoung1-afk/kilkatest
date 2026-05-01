"""Receiving .py uploads, naming the bot, replacing existing code."""

from __future__ import annotations

import logging
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bothost.config import Config
from bothost.db import BotRecord, Database
from bothost.keyboards import bot_actions_menu, cancel_keyboard
from bothost.runner import BotRunner, make_container_name, slug_name
from bothost.states import UploadBot
from bothost.validator import validate_user_script

logger = logging.getLogger(__name__)
router = Router(name="code")


async def _download(message: Message, bot: Bot) -> bytes | None:
    if message.document is None:
        return None
    if (message.document.file_size or 0) > 1024 * 1024:
        await message.answer("⚠️ Файл больше 1 МБ, пришлите поменьше.")
        return None
    if not (message.document.file_name or "").endswith(".py"):
        await message.answer("⚠️ Нужен файл с расширением <code>.py</code>.")
        return None
    buf = BytesIO()
    await bot.download(message.document, destination=buf)
    return buf.getvalue()


async def _validate_or_warn(message: Message, source: bytes) -> bool:
    result = validate_user_script(source)
    if not result.ok:
        await message.answer(f"❌ Не могу запустить:\n<code>{result.error}</code>")
        return False
    if result.warnings:
        warn_text = "\n".join(f"• {w}" for w in result.warnings)
        await message.answer(f"⚠️ Подозрительные конструкции:\n{warn_text}")
    return True


async def _start_and_report(
    message: Message,
    *,
    runner: BotRunner,
    db: Database,
    record: BotRecord,
) -> None:
    try:
        cid = await runner.start(
            tg_id=record.tg_id, bot_id=record.id, container_name=record.container_name
        )
    except Exception as exc:
        logger.exception("failed to start bot %s", record.id)
        await db.update_bot_status(bot_id=record.id, status="crashed", last_error=str(exc))
        await message.answer(f"❌ Не удалось запустить:\n<code>{exc}</code>")
        return
    await db.update_bot_status(bot_id=record.id, status="running", container_id=cid)
    fresh = await db.get_bot_by_id(record.id)
    assert fresh is not None
    await message.answer(
        f"🟢 Бот <b>{fresh.name}</b> запущен.\nКоманды управления — на кнопках ниже.",
        reply_markup=bot_actions_menu(fresh, is_running=True),
    )


@router.callback_query(F.data == "upload")
async def cb_upload(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(call.message, Message):
        await call.message.answer(
            "📤 Пришли <b>.py файл</b> со своим ботом (одним файлом, до 1 МБ).",
            reply_markup=cancel_keyboard(),
        )
    await call.answer()


@router.message(F.document)
async def handle_document(
    message: Message,
    bot: Bot,
    cfg: Config,
    db: Database,
    runner: BotRunner,
    state: FSMContext,
) -> None:
    user = message.from_user
    if user is None:
        return
    await db.upsert_user(user.id, user.username)

    sub = await db.get_subscription(user.id)
    if sub is None or not sub.is_active():
        await message.answer(
            "❌ Сначала купи подписку: /buy. Без активной подписки запустить бота нельзя."
        )
        return

    source = await _download(message, bot)
    if source is None:
        return
    if not await _validate_or_warn(message, source):
        return

    state_data = await state.get_data()
    replace_bot_id = state_data.get("replace_bot_id")
    if replace_bot_id is not None:
        # Replace code path of an existing bot.
        record = await db.get_bot_by_id(int(replace_bot_id))
        if record is None or record.tg_id != user.id:
            await state.clear()
            await message.answer("❌ Бот не найден.")
            return
        await runner.stop(record.container_name, remove=True)
        path = await runner.save_script(tg_id=user.id, bot_id=record.id, source=source)
        await db.replace_bot_file(bot_id=record.id, file_path=str(path))
        await state.clear()
        await message.answer("🔁 Код заменён, перезапускаю бота…")
        await _start_and_report(message, runner=runner, db=db, record=record)
        return

    # New bot: ask for a name first.
    bots = await db.list_bots_for_user(user.id)
    if len(bots) >= sub.bot_quota:
        await message.answer(
            f"❌ По текущему тарифу можно держать только {sub.bot_quota} "
            f"бот{'а' if 2 <= sub.bot_quota <= 4 else 'ов' if sub.bot_quota >= 5 else ''}.\n"
            "Удалите неиспользуемых через /bots или возьмите тариф побольше."
        )
        return
    if len(bots) >= cfg.max_bots_per_user:
        await message.answer("❌ Превышен глобальный лимит ботов на пользователя.")
        return

    suggested = f"bot{len(bots) + 1}"
    await state.set_state(UploadBot.waiting_for_name)
    await state.update_data(pending_source=source.decode("utf-8", errors="replace"))
    await message.answer(
        "✏️ Как назвать бота?\nЛатинские буквы/цифры/<code>_</code>/<code>-</code>, до 32 символов.\n\n"
        f"Можешь просто написать <code>{suggested}</code> или своё.",
        reply_markup=cancel_keyboard(),
    )


@router.message(UploadBot.waiting_for_name, F.text)
async def receive_bot_name(
    message: Message,
    cfg: Config,
    db: Database,
    runner: BotRunner,
    state: FSMContext,
) -> None:
    user = message.from_user
    if user is None or message.text is None:
        return
    name = slug_name(message.text)
    if name is None:
        await message.answer(
            "❌ Имя должно быть из латинских букв/цифр/<code>_</code>/<code>-</code>, до 32 символов."
        )
        return

    existing = await db.get_bot_by_name(user.id, name)
    if existing is not None:
        await message.answer("❌ Имя занято — выбери другое.")
        return

    data = await state.get_data()
    pending_source = data.get("pending_source")
    if not isinstance(pending_source, str):
        await state.clear()
        await message.answer("❌ Что-то пошло не так, повтори загрузку файла.")
        return

    source = pending_source.encode("utf-8")
    container_name_placeholder = f"bothost_user_{user.id}_pending_{name}"
    record = await db.create_bot(
        tg_id=user.id,
        name=name,
        file_path="",
        container_name=container_name_placeholder,
    )
    real_container_name = make_container_name(user.id, record.id)
    await db.set_container_name(bot_id=record.id, container_name=real_container_name)

    path = await runner.save_script(tg_id=user.id, bot_id=record.id, source=source)
    await db.replace_bot_file(bot_id=record.id, file_path=str(path))
    await state.clear()

    fresh = await db.get_bot_by_id(record.id)
    assert fresh is not None
    await message.answer("✅ Сохранил, запускаю…")
    await _start_and_report(message, runner=runner, db=db, record=fresh)
