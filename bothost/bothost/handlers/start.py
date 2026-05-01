"""/start, /help, main-menu and status callbacks."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bothost import emoji as e
from bothost.config import Config
from bothost.db import Database
from bothost.keyboards import main_menu, status_lines

router = Router(name="start")


WELCOME = (
    f"{e.SMILE} Привет! Это <b>bothost</b> — сервис, который запускает твоих Python-ботов.\n\n"
    f"Как это работает:\n"
    f"{e.COIN} Покупаешь подписку (от <b>50⭐ за 14 дней</b>).\n"
    f"{e.PAPERCLIP} Присылаешь <b>.py</b> файл или <b>.zip</b> архив с проектом — я попрошу имя и запущу.\n"
    f"{e.BOT} Можешь держать сразу несколько ботов (по тарифу).\n\n"
    f"Управление кнопками или командами:\n"
    f"• /buy — подписка\n"
    f"• /bots — мои боты\n"
    f"• /status — состояние\n"
    f"• /help — подробнее"
)

HELP = (
    f"{e.INFO} <b>Подробнее</b>\n\n"
    f"{e.BOX} <b>Изоляция:</b> бот работает в Docker (256 МБ RAM, 0.5 CPU), без root, "
    f"без доступа к хосту. Сеть ограничена.\n"
    f"{e.LOCK_CLOSED} <b>Защита:</b> блокирую коды-стиллеры (попытки читать SSH-ключи, AWS/crypto-кошельки, "
    f"браузерные профили, /etc/shadow и т.п.).\n"
    f"{e.PAPERCLIP} <b>Что можно загружать:</b>\n"
    f"  • Один файл <code>bot.py</code> до 1 МБ.\n"
    f"  • <b>ZIP-архив</b> до 5 МБ (распакованный — до 20 МБ, до 100 файлов). "
    f"В корне обязателен <code>bot.py</code>. Можно положить <code>requirements.txt</code> "
    f"(до 50 пакетов) — установлю в <code>/app/data/site-packages</code>, "
    f"git+/file:/-зависимости запрещены.\n"
    f"{e.FILE} <b>Запись на диск:</b> только в <code>/app/data</code> "
    f"(сохраняется между перезапусками). <code>/app</code> — read-only.\n"
    f"{e.CODE} <b>Уже предустановлено:</b> aiogram, pyTelegramBotAPI, python-telegram-bot, "
    f"telethon, requests, aiohttp, httpx, sqlalchemy, asyncpg, redis, pymongo/motor, "
    f"pydantic, openai, anthropic, fastapi, pillow, lxml/bs4, и ещё ~50 популярных.\n"
    f"{e.PENCIL} <b>Имя бота:</b> <code>[A-Za-z0-9_-]</code>, до 32 символов.\n\n"
    f"{e.CROSS} Размещай только свой код. За поведение бота отвечает его автор."
)


async def _show_menu(target: Message, cfg: Config, db: Database, tg_id: int) -> None:
    sub = await db.get_subscription(tg_id)
    bots = await db.list_bots_for_user(tg_id)
    has_active = sub is not None and sub.is_active()
    text = WELCOME + "\n\n" + status_lines(sub, bots)
    await target.answer(
        text,
        reply_markup=main_menu(has_active_sub=has_active, bot_count=len(bots)),
    )


@router.message(CommandStart())
async def handle_start(message: Message, cfg: Config, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.upsert_user(tg_id=user.id, username=user.username)
    await _show_menu(message, cfg, db, user.id)


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("status"))
async def handle_status(message: Message, cfg: Config, db: Database) -> None:
    if message.from_user is None:
        return
    await _show_menu(message, cfg, db, message.from_user.id)


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery) -> None:
    if isinstance(call.message, Message):
        await call.message.answer(HELP)
    await call.answer()


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, cfg: Config, db: Database) -> None:
    if call.from_user is None or not isinstance(call.message, Message):
        await call.answer()
        return
    await _show_menu(call.message, cfg, db, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "status")
async def cb_status(call: CallbackQuery, cfg: Config, db: Database) -> None:
    if call.from_user is None or not isinstance(call.message, Message):
        await call.answer()
        return
    await _show_menu(call.message, cfg, db, call.from_user.id)
    await call.answer()
