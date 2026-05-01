"""/start, /help and main-menu callbacks."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bothost.config import Config
from bothost.db import Database
from bothost.keyboards import main_menu

router = Router(name="start")


WELCOME = (
    "👋 Привет! Это <b>bothost</b> — сервис, который запускает твоего Python-бота.\n\n"
    "Как это работает:\n"
    "1️⃣ Покупаешь подписку — <b>{stars}⭐ за {days} дней</b>.\n"
    "2️⃣ Присылаешь сюда <b>один .py файл</b> со своим ботом.\n"
    "3️⃣ Я запускаю его в изолированном контейнере и держу онлайн до конца подписки.\n\n"
    "Команды:\n"
    "• /buy — купить или продлить подписку\n"
    "• /mybot — статус бота и подписки\n"
    "• /stop — остановить бот\n"
    "• /restart — перезапустить\n"
    "• /logs — последние строки логов\n"
    "• /help — подробнее"
)


HELP = (
    "ℹ️ <b>Подробнее</b>\n\n"
    "• Поддерживаются любые библиотеки из стандартного набора:\n"
    "  <code>aiogram</code>, <code>pyTelegramBotAPI</code>, <code>python-telegram-bot</code>, "
    "<code>requests</code>, <code>aiohttp</code> и т.д.\n"
    "• Файл должен содержать токен твоего бота. Можно задать его прямо в коде "
    "или прочитать из переменной окружения <code>BOT_TOKEN</code>.\n"
    "• Размер файла — до 1 МБ.\n"
    "• Лимиты контейнера: 256 МБ RAM, 0.5 CPU.\n"
    "• Если код упадёт — посмотри ошибку через /logs и перезапусти.\n\n"
    "⚠️ Размещай только свой код. За поведение бота отвечает его автор."
)


@router.message(CommandStart())
async def handle_start(message: Message, cfg: Config, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.upsert_user(tg_id=user.id, username=user.username)
    sub = await db.active_subscription(user.id)
    bot_record = await db.get_bot(user.id)
    await message.answer(
        WELCOME.format(stars=cfg.subscription_stars, days=cfg.subscription_days),
        reply_markup=main_menu(has_active_sub=sub is not None, has_bot=bot_record is not None),
    )


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(HELP)


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
    sub = await db.active_subscription(call.from_user.id)
    bot_record = await db.get_bot(call.from_user.id)
    await call.message.answer(
        WELCOME.format(stars=cfg.subscription_stars, days=cfg.subscription_days),
        reply_markup=main_menu(has_active_sub=sub is not None, has_bot=bot_record is not None),
    )
    await call.answer()
