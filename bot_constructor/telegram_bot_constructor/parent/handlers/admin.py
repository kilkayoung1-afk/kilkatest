"""Админ-панель родительского бота."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from telegram_bot_constructor.config import Settings
from telegram_bot_constructor.db.models import ChildBot, ChildBotUser, User
from telegram_bot_constructor.db.session import session_scope
from telegram_bot_constructor.emoji import (
    E_BOT,
    E_GRAPH_UP,
    E_PEOPLE,
    E_SETTINGS,
    E_STATS,
)
from telegram_bot_constructor.keyboards import inline_button, inline_kb

router = Router(name="parent.admin")


def _admin_kb():
    return inline_kb([
        [inline_button("Назад в меню", callback_data="menu", icon=E_SETTINGS)]
    ])


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message, settings: Settings) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id, settings):
        await message.answer(f"{E_BOT} У вас нет доступа.")
        return
    async with session_scope() as session:
        users_total = (await session.execute(select(func.count(User.id)))).scalar_one()
        bots_total = (await session.execute(select(func.count(ChildBot.id)))).scalar_one()
        bots_active = (
            await session.execute(
                select(func.count(ChildBot.id)).where(ChildBot.is_active.is_(True))
            )
        ).scalar_one()
        cu_total = (
            await session.execute(select(func.count(ChildBotUser.id)))
        ).scalar_one()

    text = (
        f"<b>{E_SETTINGS} Админ-панель</b>\n\n"
        f"{E_PEOPLE} Пользователей конструктора: <b>{users_total}</b>\n"
        f"{E_BOT} Дочерних ботов: <b>{bots_total}</b> "
        f"(активных: <b>{bots_active}</b>)\n"
        f"{E_STATS} Пользователей дочерних ботов: <b>{cu_total}</b>\n"
        f"{E_GRAPH_UP} Среднее ботов на юзера: "
        f"<b>{(bots_total / users_total) if users_total else 0:.2f}</b>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=_admin_kb())


@router.callback_query(F.data == "admin:home")
async def cb_admin(call: CallbackQuery, settings: Settings) -> None:
    if call.from_user is None or call.message is None or not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.edit_text(
        f"<b>{E_SETTINGS} Админ-панель</b>\n\nИспользуйте /admin для свежей сводки.",
        parse_mode=ParseMode.HTML,
        reply_markup=_admin_kb(),
    )
    await call.answer()
