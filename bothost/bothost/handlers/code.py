"""Receiving .py / .zip uploads, naming the bot, replacing existing code."""

from __future__ import annotations

import logging
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bothost import emoji as e
from bothost.bundle import (
    MAX_ARCHIVE_BYTES,
    BundleResult,
    extract_zip,
    install_requirements,
)
from bothost.config import Config
from bothost.db import BotRecord, Database
from bothost.keyboards import bot_actions_menu, cancel_keyboard
from bothost.runner import BotRunner, make_container_name, slug_name
from bothost.states import UploadBot
from bothost.validator import validate_user_script

logger = logging.getLogger(__name__)
router = Router(name="code")


# ---- helpers ----


def _is_zip(name: str) -> bool:
    return name.lower().endswith(".zip")


def _is_py(name: str) -> bool:
    return name.lower().endswith(".py")


async def _download_bytes(message: Message, bot: Bot, *, max_bytes: int) -> bytes | None:
    if message.document is None:
        return None
    if (message.document.file_size or 0) > max_bytes:
        await message.answer(
            f"{e.CROSS} Файл больше {max_bytes // 1024 // 1024 or 1} МБ — пришли поменьше."
        )
        return None
    buf = BytesIO()
    await bot.download(message.document, destination=buf)
    return buf.getvalue()


async def _validate_py_or_warn(message: Message, source: bytes) -> bool:
    result = validate_user_script(source)
    if not result.ok:
        await message.answer(f"{e.CROSS} Не могу запустить:\n<code>{result.error}</code>")
        return False
    if result.warnings:
        warn_text = "\n".join(f"• {w}" for w in result.warnings)
        await message.answer(f"{e.INFO} Подозрительные конструкции:\n{warn_text}")
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
        await message.answer(f"{e.CROSS} Не удалось запустить:\n<code>{exc}</code>")
        return
    await db.update_bot_status(bot_id=record.id, status="running", container_id=cid)
    fresh = await db.get_bot_by_id(record.id)
    assert fresh is not None
    await message.answer(
        f"{e.CHECK} Бот <b>{fresh.name}</b> запущен.\nКоманды управления — на кнопках.",
        reply_markup=bot_actions_menu(fresh, is_running=True),
    )


async def _maybe_install_deps(
    message: Message,
    *,
    runner: BotRunner,
    cfg: Config,
    record: BotRecord,
    requirements: list[str],
) -> bool:
    if not requirements:
        return True
    site_packages = runner.site_packages_dir(record.tg_id, record.id)
    progress = await message.answer(
        f"{e.LOADING} Устанавливаю {len(requirements)} зависимост"
        f"{'ь' if len(requirements) == 1 else 'и'}…"
    )
    ok, log = await install_requirements(
        requirements=requirements,
        site_packages_dir=site_packages,
        image=cfg.user_bot_image,
        docker_client=runner.docker_client(),
    )
    try:
        await progress.delete()
    except Exception:
        pass
    if not ok:
        await message.answer(f"{e.CROSS} Не удалось установить зависимости:\n<pre>{log[-1500:]}</pre>")
        return False
    await message.answer(f"{e.CHECK} Зависимости установлены.")
    return True


async def _process_payload(
    message: Message,
    *,
    runner: BotRunner,
    db: Database,
    cfg: Config,
    record: BotRecord,
    py_source: bytes | None,
    zip_bytes: bytes | None,
) -> None:
    """Place files for `record`, install deps if any, then start it."""
    if zip_bytes is not None:
        target_dir = runner.user_dir(record.tg_id, record.id)
        # Wipe except /data so user state is preserved across replacements.
        for entry in list(target_dir.iterdir()) if target_dir.exists() else []:
            if entry.name == "data":
                continue
            try:
                if entry.is_dir():
                    import shutil as _sh

                    _sh.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
            except OSError:
                pass
        target_dir.mkdir(parents=True, exist_ok=True)
        result: BundleResult = await extract_zip(
            archive_bytes=zip_bytes, target_dir=target_dir
        )
        if not result.ok:
            await message.answer(f"{e.CROSS} {result.error}")
            return
        if result.warnings:
            warn_text = "\n".join(f"• {w}" for w in result.warnings)
            await message.answer(f"{e.INFO} Замечания:\n{warn_text}")
        await db.replace_bot_file(bot_id=record.id, file_path=str(target_dir / "bot.py"))
        if result.requirements:
            if not await _maybe_install_deps(
                message,
                runner=runner,
                cfg=cfg,
                record=record,
                requirements=result.requirements,
            ):
                return
    elif py_source is not None:
        path = await runner.save_script(tg_id=record.tg_id, bot_id=record.id, source=py_source)
        await db.replace_bot_file(bot_id=record.id, file_path=str(path))
    else:
        await message.answer(f"{e.CROSS} Внутренняя ошибка: пустой payload.")
        return

    await _start_and_report(message, runner=runner, db=db, record=record)


# ---- handlers ----


@router.callback_query(F.data == "upload")
async def cb_upload(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(call.message, Message):
        await call.message.answer(
            f"{e.PAPERCLIP} Пришли <b>.py файл</b> (до 1 МБ) "
            f"или <b>.zip архив</b> (до 5 МБ) с <code>bot.py</code> в корне.\n\n"
            f"В архив можно положить <code>requirements.txt</code> — установлю зависимости.",
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
            f"{e.CROSS} Сначала купи подписку: /buy. Без активной подписки запустить бота нельзя."
        )
        return

    document = message.document
    if document is None:
        return
    name = document.file_name or ""
    is_zip = _is_zip(name)
    is_py = _is_py(name)
    if not (is_zip or is_py):
        await message.answer(
            f"{e.CROSS} Нужен файл <code>.py</code> или архив <code>.zip</code>."
        )
        return

    raw = await _download_bytes(
        message, bot, max_bytes=MAX_ARCHIVE_BYTES if is_zip else 1024 * 1024
    )
    if raw is None:
        return

    py_source: bytes | None = None
    zip_bytes: bytes | None = None
    if is_zip:
        zip_bytes = raw
    else:
        py_source = raw
        if not await _validate_py_or_warn(message, py_source):
            return

    state_data = await state.get_data()
    replace_bot_id = state_data.get("replace_bot_id")
    if replace_bot_id is not None:
        record = await db.get_bot_by_id(int(replace_bot_id))
        if record is None or record.tg_id != user.id:
            await state.clear()
            await message.answer(f"{e.CROSS} Бот не найден.")
            return
        await runner.stop(record.container_name, remove=True)
        await state.clear()
        await message.answer(f"{e.LOADING} Заменяю код, перезапускаю…")
        await _process_payload(
            message,
            runner=runner,
            db=db,
            cfg=cfg,
            record=record,
            py_source=py_source,
            zip_bytes=zip_bytes,
        )
        return

    bots = await db.list_bots_for_user(user.id)
    if len(bots) >= sub.bot_quota:
        await message.answer(
            f"{e.CROSS} По текущему тарифу можно держать только {sub.bot_quota} "
            f"бот{'а' if 2 <= sub.bot_quota <= 4 else 'ов' if sub.bot_quota >= 5 else ''}.\n"
            "Удалите неиспользуемых через /bots или возьмите тариф побольше."
        )
        return
    if len(bots) >= cfg.max_bots_per_user:
        await message.answer(f"{e.CROSS} Превышен глобальный лимит ботов на пользователя.")
        return

    suggested = f"bot{len(bots) + 1}"
    await state.set_state(UploadBot.waiting_for_name)
    if is_zip:
        await state.update_data(pending_zip_b64=raw.hex())
    else:
        assert py_source is not None
        await state.update_data(pending_source=py_source.decode("utf-8", errors="replace"))
    await message.answer(
        f"{e.PENCIL} Как назвать бота?\nЛатинские буквы/цифры/<code>_</code>/<code>-</code>, "
        f"до 32 символов.\n\nМожешь просто написать <code>{suggested}</code> или своё.",
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
            f"{e.CROSS} Имя должно быть из латинских букв/цифр/<code>_</code>/<code>-</code>, до 32 символов."
        )
        return

    existing = await db.get_bot_by_name(user.id, name)
    if existing is not None:
        await message.answer(f"{e.CROSS} Имя занято — выбери другое.")
        return

    data = await state.get_data()
    pending_source = data.get("pending_source")
    pending_zip_hex = data.get("pending_zip_b64")
    if pending_source is None and pending_zip_hex is None:
        await state.clear()
        await message.answer(f"{e.CROSS} Что-то пошло не так, повтори загрузку файла.")
        return

    py_source: bytes | None = (
        pending_source.encode("utf-8") if isinstance(pending_source, str) else None
    )
    zip_bytes: bytes | None = (
        bytes.fromhex(pending_zip_hex) if isinstance(pending_zip_hex, str) else None
    )

    container_name_placeholder = f"bothost_user_{user.id}_pending_{name}"
    record = await db.create_bot(
        tg_id=user.id,
        name=name,
        file_path="",
        container_name=container_name_placeholder,
    )
    real_container_name = make_container_name(user.id, record.id)
    await db.set_container_name(bot_id=record.id, container_name=real_container_name)
    fresh = await db.get_bot_by_id(record.id)
    assert fresh is not None
    await state.clear()

    await message.answer(f"{e.CHECK} Сохраняю…")
    await _process_payload(
        message,
        runner=runner,
        db=db,
        cfg=cfg,
        record=fresh,
        py_source=py_source,
        zip_bytes=zip_bytes,
    )
