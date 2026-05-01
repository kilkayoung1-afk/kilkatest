"""/start, /help, main-menu and status callbacks."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bothost.config import Config
from bothost.db import Database
from bothost.keyboards import main_menu, status_lines

router = Router(name="start")


WELCOME = (
    "👋 Привет! Это <b>bothost</b> — сервис, который запускает твоих Python-ботов.\n\n"
    "Как это работает:\n"
    "1️⃣ Покупаешь подписку (от <b>50⭐ за 14 дней</b>).\n"
    "2️⃣ Присылаешь <b>.py файл</b> со своим ботом — я попрошу дать ему имя и запущу.\n"
    "3️⃣ Можешь держать сразу несколько ботов (по тарифу).\n\n"
    "Управление кнопками ниже либо командами:\n"
    "• /buy — подписка\n"
    "• /bots — мои боты\n"
    "• /status — состояние\n"
    "• /help — подробнее"
)

HELP = (
    "ℹ️ <b>Подробнее</b>\n\n"
    "• Бот работает в изолированном Docker-контейнере (256 МБ RAM, 0.5 CPU).\n"
    "• Уже установлены: <code>aiogram</code>, <code>pyTelegramBotAPI</code>, "
    "<code>python-telegram-bot</code>, <code>requests</code>, <code>aiohttp</code>, <code>httpx</code>.\n"
    "• Если нужна другая библиотека — добавь её в свой <code>.py</code> через "
    "<code>subprocess.run(['pip', 'install', '...'])</code> в начале файла.\n"
    "• Размер <code>.py</code> — до 1 МБ.\n"
    "• Имя бота: латинские буквы/цифры/<code>_</code>/<code>-</code>, до 32 символов.\n"
    "• Токен своего бота указывай прямо в <code>.py</code> или читай из ENV.\n\n"
    "⚠️ Размещай только свой код. За поведение бота отвечает его автор."
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
