"""Управление дочерними ботами: список, добавление, карточка."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from telegram_bot_constructor.config import Settings
from telegram_bot_constructor.db.repo import (
    count_user_bots,
    create_bot,
    delete_bot,
    get_bot_by_id,
    get_bot_by_token,
    get_or_create_user,
    list_user_bots,
    set_bot_active,
)
from telegram_bot_constructor.db.session import session_scope
from telegram_bot_constructor.emoji import (
    E_BOT,
    E_CHECK,
    E_CROSS,
    E_DOWNLOAD,
    E_INFO,
    E_PARTY,
    E_TRASH,
)
from telegram_bot_constructor.exporter import build_export_zip
from telegram_bot_constructor.parent.menu import (
    back_to_menu_kb,
    bot_card_kb,
    main_menu_kb,
    my_bots_kb,
)
from telegram_bot_constructor.parent.states import AddBot

logger = logging.getLogger(__name__)
router = Router(name="parent.bots")


def _bot_card_text(bot, settings: Settings) -> str:
    title = bot.title or bot.username or f"id:{bot.bot_tg_id}"
    status = f"{E_CHECK} Активен" if bot.is_active else f"{E_CROSS} Выключен"
    username = f"@{bot.username}" if bot.username else "—"
    return (
        f"<b>{E_BOT} {title}</b>\n\n"
        f"{E_INFO} Username: {username}\n"
        f"{E_INFO} Статус: {status}\n"
        f"{E_INFO} ID: <code>{bot.bot_tg_id}</code>\n\n"
        "Выберите раздел для настройки:"
    )


@router.callback_query(F.data == "my_bots")
async def cb_my_bots(call: CallbackQuery) -> None:
    if call.from_user is None or call.message is None:
        await call.answer()
        return
    async with session_scope() as session:
        user = await get_or_create_user(
            session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
        )
        bots = await list_user_bots(session, user.id)
    text = (
        f"<b>{E_BOT} Ваши боты</b>\n\n"
        f"Всего: <b>{len(bots)}</b>\n"
        "Выберите бота из списка или добавьте нового."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=my_bots_kb(bots))
    await call.answer()


@router.callback_query(F.data == "add_bot")
async def cb_add_bot(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if call.from_user is None or call.message is None:
        await call.answer()
        return
    async with session_scope() as session:
        user = await get_or_create_user(
            session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
        )
        cnt = await count_user_bots(session, user.id)
    if settings.max_bots_per_user and cnt >= settings.max_bots_per_user:
        await call.answer("Достигнут лимит ботов на одного пользователя.", show_alert=True)
        return
    await state.set_state(AddBot.waiting_token)
    await call.message.edit_text(
        f"<b>{E_BOT} Добавление бота</b>\n\n"
        "Пришлите токен от @BotFather одним сообщением.\n"
        f"Формат: <code>1234567890:AAA...</code>\n\n"
        f"{E_INFO} Токен хранится локально в SQLite, никуда не отправляется.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


@router.message(AddBot.waiting_token, F.text)
async def msg_add_bot_token(message: Message, state: FSMContext) -> None:
    if message.from_user is None or message.text is None:
        return
    token = message.text.strip()
    if ":" not in token or len(token) < 30:
        await message.answer(
            f"{E_CROSS} Похоже, это не токен. Пришлите валидный токен от @BotFather."
        )
        return

    # Проверим токен через getMe
    probe = Bot(token=token)
    try:
        me = await probe.get_me()
    except TelegramUnauthorizedError:
        await message.answer(f"{E_CROSS} Telegram вернул Unauthorized — токен неверный или отозван.")
        await probe.session.close()
        return
    except Exception as exc:
        logger.warning("get_me failed: %s", exc)
        await message.answer(f"{E_CROSS} Не удалось проверить токен: {exc}")
        await probe.session.close()
        return
    finally:
        try:
            await probe.session.close()
        except Exception:
            pass

    async with session_scope() as session:
        existing = await get_bot_by_token(session, token)
        if existing is not None:
            await state.clear()
            await message.answer(
                f"{E_CROSS} Этот бот уже добавлен (id: <code>{existing.bot_tg_id}</code>).",
                parse_mode=ParseMode.HTML,
                reply_markup=back_to_menu_kb(),
            )
            return
        user = await get_or_create_user(
            session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        bot_obj = await create_bot(
            session,
            owner_id=user.id,
            token=token,
            bot_tg_id=me.id,
            username=me.username,
            title=me.full_name,
        )
        bot_id = bot_obj.id

    # Запустим бота немедленно
    from telegram_bot_constructor.child.runtime import runtime

    await runtime.start_bot_by_id(bot_id)

    await state.clear()
    await message.answer(
        f"<b>{E_PARTY} Бот добавлен и запущен!</b>\n\n"
        f"{E_INFO} Username: @{me.username}\n"
        f"{E_INFO} Откройте карточку бота, чтобы настроить /start, команды и кнопки.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data.regexp(r"^bot:\d+$"))
async def cb_bot_card(call: CallbackQuery, settings: Settings) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
    if bot is None:
        await call.answer("Бот не найден", show_alert=True)
        return
    if call.from_user and bot.owner.tg_id != call.from_user.id:
        await call.answer("Это не ваш бот", show_alert=True)
        return
    await call.message.edit_text(
        _bot_card_text(bot, settings),
        parse_mode=ParseMode.HTML,
        reply_markup=bot_card_kb(bot),
    )
    await call.answer()


@router.callback_query(F.data.regexp(r"^bot:\d+:toggle$"))
async def cb_toggle(call: CallbackQuery, settings: Settings) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None:
            await call.answer("Бот не найден", show_alert=True)
            return
        if call.from_user and bot.owner.tg_id != call.from_user.id:
            await call.answer("Это не ваш бот", show_alert=True)
            return
        new_active = not bot.is_active
        await set_bot_active(session, bot_id, new_active)

    from telegram_bot_constructor.child.runtime import runtime

    if new_active:
        await runtime.start_bot_by_id(bot_id)
    else:
        await runtime.stop_bot(bot_id)

    await call.answer("Включен" if new_active else "Выключен")

    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
    if bot is not None:
        await call.message.edit_text(
            _bot_card_text(bot, settings),
            parse_mode=ParseMode.HTML,
            reply_markup=bot_card_kb(bot),
        )


@router.callback_query(F.data.regexp(r"^bot:\d+:del$"))
async def cb_delete(call: CallbackQuery) -> None:
    if call.message is None or call.data is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        bot = await get_bot_by_id(session, bot_id)
        if bot is None:
            await call.answer("Бот не найден", show_alert=True)
            return
        if call.from_user and bot.owner.tg_id != call.from_user.id:
            await call.answer("Это не ваш бот", show_alert=True)
            return

    from telegram_bot_constructor.child.runtime import runtime

    await runtime.stop_bot(bot_id)

    async with session_scope() as session:
        await delete_bot(session, bot_id)

    await call.message.edit_text(
        f"{E_TRASH} Бот удалён.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_to_menu_kb(),
    )
    await call.answer("Удалено")


@router.callback_query(F.data.regexp(r"^bot:\d+:export$"))
async def cb_export(call: CallbackQuery, bot: Bot) -> None:
    """Собрать и отправить владельцу zip с standalone-кодом дочернего бота."""
    if call.message is None or call.data is None or call.from_user is None:
        await call.answer()
        return
    bot_id = int(call.data.split(":")[1])
    async with session_scope() as session:
        target = await get_bot_by_id(session, bot_id)
        if target is None:
            await call.answer("Бот не найден", show_alert=True)
            return
        if target.owner.tg_id != call.from_user.id:
            await call.answer("Это не ваш бот", show_alert=True)
            return

        try:
            me = await bot.get_me()
            constructor_username = me.username
            constructor_title = me.full_name
        except Exception as exc:  # pragma: no cover - сетевая ошибка
            logger.warning("get_me for constructor failed: %s", exc)
            constructor_username = None
            constructor_title = None

        archive = await build_export_zip(
            session,
            bot_id,
            constructor_username=constructor_username,
            constructor_title=constructor_title,
        )

    title = target.title or target.username or f"bot_{bot_id}"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in title).strip("_") or "bot"
    filename = f"{safe[:48]}.zip"

    await call.answer("Готовлю архив…")
    await bot.send_document(
        chat_id=call.from_user.id,
        document=BufferedInputFile(archive, filename=filename),
        caption=(
            f"<b>{E_DOWNLOAD} Код вашего бота</b>\n\n"
            f"Запуск: распакуйте архив, поставьте зависимости из <code>requirements.txt</code>, "
            f"положите <code>BOT_TOKEN</code> в <code>.env</code> и запустите <code>python bot.py</code>.\n\n"
            f"{E_INFO} В <code>/start</code> выгруженного бота добавлен футер "
            f"«Создано с помощью {('@' + constructor_username) if constructor_username else 'конструктора'}»."
        ),
        parse_mode=ParseMode.HTML,
    )
