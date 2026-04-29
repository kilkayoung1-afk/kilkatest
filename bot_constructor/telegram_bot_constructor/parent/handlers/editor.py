"""Редактор: текст /start, команды, текстовые триггеры."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from telegram_bot_constructor.db.repo import (
    create_command,
    create_trigger,
    delete_command,
    delete_trigger,
    get_bot_by_id,
    get_command_by_id,
    get_trigger_by_id,
    list_commands,
    list_triggers,
)
from telegram_bot_constructor.db.session import session_scope
from telegram_bot_constructor.emoji import (
    E_CHECK,
    E_CROSS,
    E_INFO,
    E_MEGAPHONE,
    E_PENCIL,
    E_SETTINGS,
    E_TRASH,
)
from telegram_bot_constructor.keyboards import inline_button, inline_kb
from telegram_bot_constructor.parent.states import (
    AddCommand,
    AddTrigger,
    EditStartMessage,
)

router = Router(name="parent.editor")


def _back_kb(bot_id: int):
    return inline_kb([
        [inline_button("К боту", callback_data=f"bot:{bot_id}", icon=E_SETTINGS)]
    ])


# ---------- Текст /start ---------------------------------------------------


@router.callback_query(F.data.regexp(r"^bot:\d+:start$"))
async def cb_edit_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        current = bot.start_text or "—"
    await state.set_state(EditStartMessage.waiting_text)
    await state.update_data(bot_id=bot_id)
    await call.message.edit_text(
        f"<b>{E_PENCIL} Текст /start</b>\n\n"
        f"Текущий:\n<blockquote>{current}</blockquote>\n\n"
        f"{E_INFO} Пришлите новый текст. Поддерживается HTML и premium-эмодзи через "
        f'<code>&lt;tg-emoji emoji-id="..."&gt;X&lt;/tg-emoji&gt;</code>.',
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )
    await call.answer()


@router.message(EditStartMessage.waiting_text, F.text)
async def msg_edit_start(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    bot_id = int(data.get("bot_id", 0))
    if not bot_id or message.text is None:
        await state.clear()
        return
    text = message.html_text  # сохраняем форматирование
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (message.from_user and bot.owner.tg_id != message.from_user.id):
            await message.answer("Нет доступа")
            await state.clear()
            return
        bot.start_text = text
    await state.clear()
    await message.answer(
        f"{E_CHECK} Текст /start обновлён.",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )


# ---------- Команды --------------------------------------------------------


def _commands_kb(bot_id: int, commands) -> InlineKeyboardMarkup:  # type: ignore[name-defined]
    rows = []
    for c in commands:
        rows.append([
            inline_button(f"/{c.command}", callback_data=f"cmd:{c.id}", icon=E_PENCIL),
            inline_button("Удалить", callback_data=f"cmd:del:{c.id}", icon=E_TRASH),
        ])
    rows.append([
        inline_button("Добавить команду", callback_data=f"bot:{bot_id}:cmd_add", icon=E_SETTINGS),
    ])
    rows.append([
        inline_button("К боту", callback_data=f"bot:{bot_id}", icon=E_SETTINGS),
    ])
    return inline_kb(rows)


@router.callback_query(F.data.regexp(r"^bot:\d+:cmds$"))
async def cb_commands_list(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        commands = await list_commands(session, bot_id)

    text = (
        f"<b>{E_SETTINGS} Команды бота</b>\n\n"
        f"Всего: <b>{len(commands)}</b>\n"
        f"{E_INFO} Реакции на команды вида <code>/help</code>, <code>/info</code> и т.п."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_commands_kb(bot_id, commands))
    await call.answer()


@router.callback_query(F.data.regexp(r"^bot:\d+:cmd_add$"))
async def cb_command_add(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    await state.set_state(AddCommand.waiting_command)
    await state.update_data(bot_id=bot_id)
    await call.message.edit_text(
        f"<b>{E_SETTINGS} Новая команда</b>\n\n"
        "Пришлите имя команды без слэша. Пример: <code>help</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )
    await call.answer()


@router.message(AddCommand.waiting_command, F.text)
async def msg_command_name(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    cmd = message.text.strip().lstrip("/").lower()
    if not cmd or not cmd.replace("_", "").isalnum() or len(cmd) > 32:
        await message.answer(f"{E_CROSS} Неверное имя команды. Только латиница, цифры и _.")
        return
    await state.update_data(command=cmd)
    await state.set_state(AddCommand.waiting_response)
    await message.answer(
        f"<b>{E_PENCIL} Ответ на /{cmd}</b>\n\n"
        "Пришлите текст, который бот будет отправлять. Поддерживается HTML.",
        parse_mode=ParseMode.HTML,
    )


@router.message(AddCommand.waiting_response, F.text)
async def msg_command_response(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    bot_id = int(data.get("bot_id", 0))
    cmd = data.get("command", "")
    if not bot_id or not cmd or message.text is None:
        await state.clear()
        return
    response = message.html_text
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (message.from_user and bot.owner.tg_id != message.from_user.id):
            await message.answer("Нет доступа")
            await state.clear()
            return
        await create_command(session, bot_id=bot_id, command=cmd, response_text=response)
    await state.clear()
    await message.answer(
        f"{E_CHECK} Команда /{cmd} добавлена.",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )


@router.callback_query(F.data.regexp(r"^cmd:del:\d+$"))
async def cb_command_delete(call: CallbackQuery) -> None:
    if call.data is None:
        await call.answer()
        return
    cmd_id = int(call.data.split(":")[2])
    async with session_scope() as session:
        cmd = await get_command_by_id(session, cmd_id)
        if cmd is None:
            await call.answer("Не найдено", show_alert=True)
            return
        bot = await get_bot_by_id(session, cmd.bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        bot_id = cmd.bot_id
        await delete_command(session, cmd_id)
    await call.answer("Удалено")
    # обновим список
    async with session_scope() as session:
        commands = await list_commands(session, bot_id)
    if call.message is not None:
        await call.message.edit_text(
            f"<b>{E_SETTINGS} Команды бота</b>\n\nВсего: <b>{len(commands)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=_commands_kb(bot_id, commands),
        )


# ---------- Триггеры -------------------------------------------------------


def _triggers_kb(bot_id: int, triggers) -> InlineKeyboardMarkup:  # type: ignore[name-defined]
    rows = []
    for t in triggers:
        rows.append([
            inline_button(f"{t.match_type}: {t.pattern[:24]}", callback_data=f"trig:{t.id}", icon=E_MEGAPHONE),
            inline_button("Удалить", callback_data=f"trig:del:{t.id}", icon=E_TRASH),
        ])
    rows.append([
        inline_button("Добавить триггер", callback_data=f"bot:{bot_id}:trig_add", icon=E_SETTINGS)
    ])
    rows.append([
        inline_button("К боту", callback_data=f"bot:{bot_id}", icon=E_SETTINGS)
    ])
    return inline_kb(rows)


@router.callback_query(F.data.regexp(r"^bot:\d+:trig$"))
async def cb_triggers_list(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        triggers = await list_triggers(session, bot_id)
    text = (
        f"<b>{E_MEGAPHONE} Триггеры</b>\n\n"
        f"Всего: <b>{len(triggers)}</b>\n"
        f"{E_INFO} Реакция на сообщения по совпадению (exact / contains / startswith)."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_triggers_kb(bot_id, triggers))
    await call.answer()


@router.callback_query(F.data.regexp(r"^bot:\d+:trig_add$"))
async def cb_trigger_add(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    await state.set_state(AddTrigger.waiting_pattern)
    await state.update_data(bot_id=bot_id, match_type="contains")
    await call.message.edit_text(
        f"<b>{E_MEGAPHONE} Новый триггер</b>\n\n"
        "Пришлите фразу для срабатывания (по подстроке, без учёта регистра).",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )
    await call.answer()


@router.message(AddTrigger.waiting_pattern, F.text)
async def msg_trigger_pattern(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    pattern = message.text.strip()
    if not pattern:
        await message.answer(f"{E_CROSS} Пустой паттерн.")
        return
    await state.update_data(pattern=pattern)
    await state.set_state(AddTrigger.waiting_response)
    await message.answer(
        f"<b>{E_PENCIL} Ответ на «{pattern}»</b>\n\n"
        "Пришлите текст ответа (HTML поддерживается).",
        parse_mode=ParseMode.HTML,
    )


@router.message(AddTrigger.waiting_response, F.text)
async def msg_trigger_response(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    bot_id = int(data.get("bot_id", 0))
    pattern = data.get("pattern")
    match_type = data.get("match_type", "contains")
    if not bot_id or not pattern or message.text is None:
        await state.clear()
        return
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None or (message.from_user and bot.owner.tg_id != message.from_user.id):
            await message.answer("Нет доступа")
            await state.clear()
            return
        await create_trigger(
            session,
            bot_id=bot_id,
            pattern=pattern,
            response_text=message.html_text,
            match_type=match_type,
        )
    await state.clear()
    await message.answer(
        f"{E_CHECK} Триггер добавлен.",
        parse_mode=ParseMode.HTML,
        reply_markup=_back_kb(bot_id),
    )


@router.callback_query(F.data.regexp(r"^trig:del:\d+$"))
async def cb_trigger_delete(call: CallbackQuery) -> None:
    if call.data is None:
        await call.answer()
        return
    trig_id = int(call.data.split(":")[2])
    async with session_scope() as session:
        trig = await get_trigger_by_id(session, trig_id)
        if trig is None:
            await call.answer("Не найдено", show_alert=True)
            return
        bot = await get_bot_by_id(session, trig.bot_id)
        if bot is None or (call.from_user and bot.owner.tg_id != call.from_user.id):
            await call.answer("Нет доступа", show_alert=True)
            return
        bot_id = trig.bot_id
        await delete_trigger(session, trig_id)
    await call.answer("Удалено")
    async with session_scope() as session:
        triggers = await list_triggers(session, bot_id)
    if call.message is not None:
        await call.message.edit_text(
            f"<b>{E_MEGAPHONE} Триггеры</b>\n\nВсего: <b>{len(triggers)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=_triggers_kb(bot_id, triggers),
        )
