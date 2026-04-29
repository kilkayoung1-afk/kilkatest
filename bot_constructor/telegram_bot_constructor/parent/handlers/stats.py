"""Статистика и подписочный гейт."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot_constructor.db.repo import (
    child_user_active_24h,
    child_user_count,
    get_bot_by_id,
    list_child_users,
)
from telegram_bot_constructor.db.session import session_scope
from telegram_bot_constructor.emoji import (
    E_CHECK,
    E_CROSS,
    E_GRAPH_UP,
    E_INFO,
    E_LOCK_CLOSED,
    E_LOCK_OPEN,
    E_PEOPLE,
    E_SETTINGS,
    E_STATS,
)
from telegram_bot_constructor.keyboards import inline_button, inline_kb
from telegram_bot_constructor.parent.states import SubscribeGate

router = Router(name="parent.stats")


def _back_kb(bot_id: int):
    return inline_kb([
        [inline_button("К боту", callback_data=f"bot:{bot_id}", icon=E_SETTINGS)]
    ])


@router.callback_query(F.data.regexp(r"^bot:\d+:stat$"))
async def cb_stats(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        total = await child_user_count(session, bot_id)
        active = await child_user_active_24h(session, bot_id)
    text = (
        f"<b>{E_STATS} Статистика бота</b>\n\n"
        f"{E_PEOPLE} Всего пользователей: <b>{total}</b>\n"
        f"{E_GRAPH_UP} Активные за 24 часа: <b>{active}</b>\n"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_back_kb(bot_id))
    await call.answer()


@router.callback_query(F.data.regexp(r"^bot:\d+:users$"))
async def cb_users(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        users = await list_child_users(session, bot_id)
    lines = [f"<b>{E_PEOPLE} Пользователи (всего {len(users)})</b>", ""]
    for u in users[:50]:
        username = f"@{u.username}" if u.username else "—"
        lines.append(f"• <code>{u.tg_id}</code> {username} {u.first_name or ''}")
    if len(users) > 50:
        lines.append(f"\n{E_INFO} Показаны первые 50.")
    await call.message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=_back_kb(bot_id))
    await call.answer()


# ---------- Подписка-гейт --------------------------------------------------


@router.callback_query(F.data.regexp(r"^bot:\d+:sub$"))
async def cb_sub(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        cur_chan = bot.subscribe_channel or "—"
        cur_link = bot.subscribe_link or "—"

    text = (
        f"<b>{E_LOCK_CLOSED} Подписка-гейт</b>\n\n"
        f"{E_INFO} Текущий канал: <code>{cur_chan}</code>\n"
        f"{E_INFO} Ссылка: <code>{cur_link}</code>\n\n"
        "Введите username канала (например <code>@my_channel</code>) или /off, чтобы отключить."
    )
    await state.set_state(SubscribeGate.waiting_channel)
    await state.update_data(bot_id=bot_id)
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_back_kb(bot_id))
    await call.answer()


@router.message(SubscribeGate.waiting_channel, F.text)
async def msg_sub_channel(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    data = await state.get_data()
    bot_id = int(data.get("bot_id", 0))
    if not bot_id:
        await state.clear()
        return
    raw = message.text.strip()
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (message.from_user and bot.owner.tg_id != message.from_user.id):
            await state.clear()
            return
        if raw.lower() in {"/off", "off", "выкл"}:
            bot.subscribe_channel = None
            bot.subscribe_link = None
            await state.clear()
            await message.answer(
                f"{E_LOCK_OPEN} Подписка-гейт отключён.",
                parse_mode=ParseMode.HTML,
                reply_markup=_back_kb(bot_id),
            )
            return
        channel = raw if raw.startswith("@") else f"@{raw}"
        bot.subscribe_channel = channel

    await state.update_data(channel=channel)
    await state.set_state(SubscribeGate.waiting_link)
    await message.answer(
        f"{E_INFO} Теперь пришлите ссылку на канал (https://t.me/...) — она показывается в кнопке."
    )


@router.message(SubscribeGate.waiting_link, F.text)
async def msg_sub_link(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    data = await state.get_data()
    bot_id = int(data.get("bot_id", 0))
    link = message.text.strip()
    if not link.startswith("http"):
        await message.answer(f"{E_CROSS} Ссылка должна начинаться с http(s)://")
        return
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None:
            await state.clear()
            return
        bot.subscribe_link = link
    await state.clear()
    await message.answer(
        f"{E_CHECK} Подписка-гейт настроен.",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )
