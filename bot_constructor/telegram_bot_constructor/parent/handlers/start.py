"""Стартовое меню родительского бота."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from telegram_bot_constructor.db.repo import get_or_create_user
from telegram_bot_constructor.db.session import session_scope
from telegram_bot_constructor.emoji import E_BOT, E_INFO, E_PARTY, E_SETTINGS
from telegram_bot_constructor.parent.menu import back_to_menu_kb, main_menu_kb

router = Router(name="parent.start")


WELCOME = (
    f"<b>{E_PARTY} Добро пожаловать в конструктор ботов!</b>\n\n"
    f"{E_BOT} Создавайте сколько угодно Telegram-ботов — бесплатно.\n"
    f"{E_SETTINGS} Настраивайте команды, кнопки и рассылки.\n"
    f"{E_INFO} Используются premium-эмодзи для красивого UI.\n\n"
    "Чтобы добавить нового бота — нажмите кнопку ниже."
)


HELP_TEXT = (
    f"<b>{E_INFO} Как пользоваться</b>\n\n"
    "1. Создайте бота у @BotFather, скопируйте токен.\n"
    "2. Нажмите <b>Добавить бота</b> и пришлите токен.\n"
    "3. В карточке бота настройте: текст /start, команды, триггеры,\n"
    "   inline и reply клавиатуры с premium-эмодзи, рассылку.\n"
    "4. Бот сразу начнёт работать — кнопкой можно выключить."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    async with session_scope() as session:
        await get_or_create_user(
            session,
            tg_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )
    await message.answer(WELCOME, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery) -> None:
    if call.message is None:
        await call.answer()
        return
    await call.message.edit_text(
        WELCOME, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
    )
    await call.answer()


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery) -> None:
    if call.message is None:
        await call.answer()
        return
    await call.message.edit_text(
        HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=back_to_menu_kb()
    )
    await call.answer()
