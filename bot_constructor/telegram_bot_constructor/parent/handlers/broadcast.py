"""Рассылка по пользователям дочернего бота."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot_constructor.db.repo import (
    get_bot_by_id,
    list_child_users,
    log_broadcast,
)
from telegram_bot_constructor.db.session import session_scope
from telegram_bot_constructor.emoji import (
    E_CHECK,
    E_CROSS,
    E_INFO,
    E_LOADING,
    E_MEGAPHONE,
    E_SETTINGS,
)
from telegram_bot_constructor.keyboards import inline_button, inline_kb
from telegram_bot_constructor.parent.states import Broadcast

logger = logging.getLogger(__name__)
router = Router(name="parent.broadcast")


def _back_kb(bot_id: int):
    return inline_kb([
        [inline_button("К боту", callback_data=f"bot:{bot_id}", icon=E_SETTINGS)]
    ])


@router.callback_query(F.data.regexp(r"^bot:\d+:cast$"))
async def cb_broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
    await state.set_state(Broadcast.waiting_message)
    await state.update_data(bot_id=bot_id)
    await call.message.edit_text(
        f"<b>{E_MEGAPHONE} Рассылка</b>\n\n"
        f"{E_INFO} Пришлите сообщение, которое будет отправлено всем пользователям бота.\n"
        "Поддерживается HTML.",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )
    await call.answer()


@router.message(Broadcast.waiting_message, F.text)
async def msg_broadcast_collect(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    data = await state.get_data()
    bot_id = int(data.get("bot_id", 0))
    if not bot_id:
        await state.clear()
        return
    text = message.html_text
    await state.update_data(text=text)
    await state.set_state(Broadcast.confirm)

    async with session_scope() as session:
        users = await list_child_users(session, bot_id)
    await message.answer(
        f"<b>{E_INFO} Подтвердите рассылку</b>\n\n"
        f"Получатели: <b>{len(users)}</b>\n\n"
        f"Превью:\n<blockquote>{text}</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=inline_kb([
            [inline_button("Отправить", callback_data="cast:go", icon=E_CHECK)],
            [inline_button("Отмена", callback_data=f"bot:{bot_id}", icon=E_CROSS)],
        ]),
    )


@router.callback_query(Broadcast.confirm, F.data == "cast:go")
async def cb_broadcast_go(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return
    data = await state.get_data()
    bot_id = int(data.get("bot_id", 0))
    text = data.get("text", "")
    if not bot_id or not text:
        await state.clear()
        await call.answer()
        return

    async with session_scope() as session:
        bot_obj = await get_bot_by_id(session, bot_id)
        users = await list_child_users(session, bot_id)
    if bot_obj is None:
        await call.answer("Бот не найден", show_alert=True)
        return

    await call.message.edit_text(
        f"{E_LOADING} Идёт рассылка по {len(users)} пользователям...",
        parse_mode=ParseMode.HTML,
    )

    bot = Bot(token=bot_obj.token)
    delivered = 0
    failed = 0
    try:
        for u in users:
            try:
                await bot.send_message(u.tg_id, text, parse_mode=ParseMode.HTML)
                delivered += 1
            except TelegramAPIError as exc:
                failed += 1
                logger.debug("broadcast %s -> %s failed: %s", bot_id, u.tg_id, exc)
            # ~30 msg/sec лимит Telegram, оставим запас
            await asyncio.sleep(0.05)
    finally:
        await bot.session.close()

    async with session_scope() as session:
        await log_broadcast(
            session,
            bot_id=bot_id,
            text=text,
            total=len(users),
            delivered=delivered,
            failed=failed,
        )
    await state.clear()
    await call.message.edit_text(
        f"<b>{E_CHECK} Рассылка завершена</b>\n\n"
        f"{E_INFO} Доставлено: <b>{delivered}</b>\n"
        f"{E_CROSS} Ошибки: <b>{failed}</b>\n"
        f"{E_INFO} Всего: <b>{len(users)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )
    await call.answer()
