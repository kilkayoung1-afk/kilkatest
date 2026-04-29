"""Редактор клавиатур (inline / reply) с premium emoji."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from telegram_bot_constructor.db.models import Keyboard, KeyboardButton
from telegram_bot_constructor.db.repo import (
    add_button,
    create_keyboard,
    delete_button,
    delete_keyboard,
    get_bot_by_id,
    get_keyboard,
    list_keyboards,
)
from telegram_bot_constructor.db.session import session_scope
from telegram_bot_constructor.emoji import (
    E_BOT,
    E_CHECK,
    E_CODE,
    E_CROSS,
    E_INFO,
    E_LINK,
    E_MEGAPHONE,
    E_PENCIL,
    E_SETTINGS,
    E_TRASH,
    EMOJI_BY_NAME,
)
from telegram_bot_constructor.keyboards import inline_button, inline_kb
from telegram_bot_constructor.parent.states import AddButton, AddKeyboard

router = Router(name="parent.keyboards")


def _back_to_bot(bot_id: int):
    return inline_kb([
        [inline_button("К боту", callback_data=f"bot:{bot_id}", icon=E_SETTINGS)]
    ])


def _kbs_kb(bot_id: int, kbs: list[Keyboard]):
    rows = []
    for kb in kbs:
        icon = E_LINK if kb.kind == "inline" else E_CODE
        rows.append([
            inline_button(f"{kb.kind}: {kb.title}", callback_data=f"kb:{kb.id}", icon=icon)
        ])
    rows.append([
        inline_button("Inline-клавиатура", callback_data=f"bot:{bot_id}:kb_add:inline", icon=E_LINK),
        inline_button("Reply-клавиатура", callback_data=f"bot:{bot_id}:kb_add:reply", icon=E_CODE),
    ])
    rows.append([
        inline_button("К боту", callback_data=f"bot:{bot_id}", icon=E_SETTINGS),
    ])
    return inline_kb(rows)


@router.callback_query(F.data.regexp(r"^bot:\d+:kbs$"))
async def cb_kbs_list(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        kbs = await list_keyboards(session, bot_id)
    await call.message.edit_text(
        f"<b>{E_SETTINGS} Клавиатуры</b>\n\n"
        f"Всего: <b>{len(kbs)}</b>\n"
        f"{E_INFO} Кнопки используют premium-эмодзи.",
        parse_mode=ParseMode.HTML,
        reply_markup=_kbs_kb(bot_id, kbs),
    )
    await call.answer()


@router.callback_query(F.data.regexp(r"^bot:\d+:kb_add:(inline|reply)$"))
async def cb_kb_add(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    parts = call.data.split(":")
    bot_id = int(parts[1])
    kind = parts[3]
    await state.set_state(AddKeyboard.waiting_title)
    await state.update_data(bot_id=bot_id, kind=kind)
    await call.message.edit_text(
        f"<b>{E_PENCIL} Новая {kind}-клавиатура</b>\n\n"
        "Пришлите название (для удобства).",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_to_bot(bot_id),
    )
    await call.answer()


@router.message(AddKeyboard.waiting_title, F.text)
async def msg_kb_title(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    title = message.text.strip()[:64]
    data = await state.get_data()
    bot_id = int(data.get("bot_id", 0))
    kind = data.get("kind", "inline")
    if not bot_id:
        await state.clear()
        return
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (message.from_user and bot.owner.tg_id != message.from_user.id):
            await message.answer("Нет доступа")
            await state.clear()
            return
        kb = await create_keyboard(session, bot_id=bot_id, kind=kind, title=title)
        kb_id = kb.id
    await state.clear()
    await message.answer(
        f"{E_CHECK} Создано. Теперь добавьте кнопки.",
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_card_kb(kb_id, kind),
    )


def _kb_card_kb(kb_id: int, kind: str):
    return inline_kb([
        [inline_button("Добавить кнопку", callback_data=f"kb:{kb_id}:btn_add", icon=E_PENCIL)],
        [inline_button("Удалить клавиатуру", callback_data=f"kb:{kb_id}:del", icon=E_TRASH)],
        [inline_button("Назад", callback_data=f"kb:{kb_id}:back", icon=E_SETTINGS)],
    ])


async def _kb_full_view(kb_id: int) -> tuple[str, InlineKeyboardMarkup, int] | None:  # type: ignore[name-defined]
    async with session_scope() as session:
        res = await session.execute(
            select(Keyboard)
            .where(Keyboard.id == kb_id)
            .options(selectinload(Keyboard.buttons))
        )
        kb = res.scalar_one_or_none()
        if kb is None:
            return None
        bot_id = kb.bot_id
        lines = [f"<b>{E_SETTINGS} Клавиатура: {kb.title} ({kb.kind})</b>", ""]
        if not kb.buttons:
            lines.append(f"{E_INFO} Кнопок ещё нет.")
        else:
            for b in kb.buttons:
                emoji = ""
                if b.icon_custom_emoji_id:
                    emoji = f' [icon: <code>{b.icon_custom_emoji_id}</code>]'
                lines.append(
                    f"r{b.row}c{b.col}: <b>{b.text}</b> — {b.action}: <code>{b.payload or ''}</code>{emoji}"
                )
        text = "\n".join(lines)
        rows = []
        for b in kb.buttons:
            rows.append([
                inline_button(f"r{b.row}c{b.col} {b.text[:20]}", callback_data=f"kb:{kb_id}:btn:{b.id}", icon=E_PENCIL),
                inline_button("Удалить", callback_data=f"kb:{kb_id}:btn_del:{b.id}", icon=E_TRASH),
            ])
        rows.append([
            inline_button("Добавить кнопку", callback_data=f"kb:{kb_id}:btn_add", icon=E_PENCIL),
        ])
        rows.append([
            inline_button("Удалить клавиатуру", callback_data=f"kb:{kb_id}:del", icon=E_TRASH),
            inline_button("К списку", callback_data=f"bot:{bot_id}:kbs", icon=E_SETTINGS),
        ])
        return text, inline_kb(rows), bot_id


@router.callback_query(F.data.regexp(r"^kb:\d+$"))
async def cb_kb_card(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    kb_id = int(call.data.split(":")[1])
    view = await _kb_full_view(kb_id)
    if view is None:
        await call.answer("Не найдено", show_alert=True)
        return
    text, kb_markup, _ = view
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_markup)
    await call.answer()


@router.callback_query(F.data.regexp(r"^kb:\d+:del$"))
async def cb_kb_delete(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    kb_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        kb = await get_keyboard(session, kb_id)
        if kb is None:
            await call.answer("Не найдено", show_alert=True)
            return
        bot_id = kb.bot_id
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        await delete_keyboard(session, kb_id)
    await call.answer("Удалено")
    async with session_scope() as session:
        kbs = await list_keyboards(session, bot_id)
    await call.message.edit_text(
        f"<b>{E_SETTINGS} Клавиатуры</b>\n\nВсего: <b>{len(kbs)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=_kbs_kb(bot_id, kbs),
    )


# ---------- Кнопки клавиатуры ----------------------------------------------


@router.callback_query(F.data.regexp(r"^kb:\d+:btn_add$"))
async def cb_btn_add(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    kb_id = int(call.data.split(":")[1])
    await state.set_state(AddButton.waiting_text)
    await state.update_data(kb_id=kb_id)
    await call.message.edit_text(
        f"<b>{E_PENCIL} Новая кнопка</b>\n\nПришлите текст кнопки.",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(AddButton.waiting_text, F.text)
async def msg_btn_text(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    await state.update_data(text=message.text.strip()[:64])
    await state.set_state(AddButton.waiting_emoji)
    rows = []
    cur: list = []
    for name, em in EMOJI_BY_NAME.items():
        cur.append(inline_button(name, callback_data=f"emo:{em.emoji_id}", icon=em))
        if len(cur) == 3:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append([inline_button("Без иконки", callback_data="emo:none", icon=E_CROSS)])
    await message.answer(
        f"<b>{E_BOT} Premium-эмодзи на иконку кнопки?</b>\n\n"
        f"{E_INFO} Выберите иконку или нажмите «Без иконки».",
        parse_mode=ParseMode.HTML,
        reply_markup=inline_kb(rows),
    )


@router.callback_query(AddButton.waiting_emoji, F.data.regexp(r"^emo:"))
async def cb_btn_emoji(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    val = call.data.split(":", 1)[1]
    icon_id = None if val == "none" else val
    await state.update_data(icon=icon_id)
    await state.set_state(AddButton.waiting_action)
    await call.message.edit_text(
        f"<b>{E_SETTINGS} Действие кнопки</b>\n\n"
        "Выберите тип:\n"
        f"• {E_LINK} URL — кнопка-ссылка (для inline)\n"
        f"• {E_MEGAPHONE} Reply — отправляет текст в чат\n"
        f"• {E_CODE} Callback — внутренний обработчик",
        parse_mode=ParseMode.HTML,
        reply_markup=inline_kb([
            [inline_button("URL", callback_data="act:url", icon=E_LINK)],
            [inline_button("Reply", callback_data="act:reply", icon=E_MEGAPHONE)],
            [inline_button("Callback", callback_data="act:callback", icon=E_CODE)],
        ]),
    )
    await call.answer()


@router.callback_query(AddButton.waiting_action, F.data.regexp(r"^act:(url|reply|callback)$"))
async def cb_btn_action(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    action = call.data.split(":", 1)[1]
    await state.update_data(action=action)
    await state.set_state(AddButton.waiting_payload)
    if action == "url":
        prompt = "Пришлите URL (https://...)."
    elif action == "reply":
        prompt = "Пришлите текст, который будет отправлен в чат при нажатии."
    else:
        prompt = "Пришлите callback_data (короткая строка-идентификатор)."
    await call.message.edit_text(
        f"<b>{E_PENCIL} Параметр кнопки</b>\n\n{prompt}",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(AddButton.waiting_payload, F.text)
async def msg_btn_payload(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    data = await state.get_data()
    kb_id = int(data.get("kb_id", 0))
    text = data.get("text", "")
    icon = data.get("icon")
    action = data.get("action", "callback")
    payload = message.text.strip()
    if not kb_id or not text or not payload:
        await state.clear()
        return
    async with session_scope() as session:
        kb = await get_keyboard(session, kb_id)
        if kb is None:
            await message.answer("Клавиатура не найдена")
            await state.clear()
            return
        bot = await get_bot_by_id(session, kb.bot_id)
        if bot is None or (message.from_user and bot.owner.tg_id != message.from_user.id):
            await message.answer("Нет доступа")
            await state.clear()
            return
        # Размещаем по 2 кнопки в ряд
        existing = await session.execute(
            select(KeyboardButton).where(KeyboardButton.keyboard_id == kb_id)
        )
        existing_btns = list(existing.scalars().all())
        n = len(existing_btns)
        row = n // 2
        col = n % 2
        await add_button(
            session,
            keyboard_id=kb_id,
            text=text,
            icon_custom_emoji_id=icon,
            action=action,
            payload=payload,
            row=row,
            col=col,
        )
    await state.clear()
    view = await _kb_full_view(kb_id)
    if view is not None:
        view_text, kb_markup, _ = view
        await message.answer(
            f"{E_CHECK} Кнопка добавлена.\n\n{view_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_markup,
        )


@router.callback_query(F.data.regexp(r"^kb:\d+:btn_del:\d+$"))
async def cb_btn_del(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    parts = call.data.split(":")
    kb_id = int(parts[1])
    btn_id = int(parts[3])
    async with session_scope() as session:
        kb = await get_keyboard(session, kb_id)
        if kb is None:
            await call.answer("Не найдено", show_alert=True)
            return
        bot = await get_bot_by_id(session, kb.bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        await delete_button(session, btn_id)
    await call.answer("Удалено")
    view = await _kb_full_view(kb_id)
    if view is not None:
        text, kb_markup, _ = view
        await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_markup)
