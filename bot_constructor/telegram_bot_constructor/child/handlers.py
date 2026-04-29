"""Динамические хендлеры для дочерних ботов.

Хендлеры читают конфигурацию из БД на каждое событие. Это упрощает
обновление настроек: пользователю не нужно перезапускать бота после
изменения команд / триггеров / клавиатур.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from telegram_bot_constructor.db.models import (
    BotCommand,
    BotTrigger,
    ChildBot,
    Keyboard,
)
from telegram_bot_constructor.db.repo import (
    get_bot_by_id,
    upsert_child_user,
)
from telegram_bot_constructor.db.session import session_scope
from telegram_bot_constructor.emoji import E_CHECK, E_CROSS, E_LOCK_CLOSED, E_PARTY
from telegram_bot_constructor.keyboards import (
    build_inline_from_db,
    build_reply_from_db,
    inline_button,
    inline_kb,
)

logger = logging.getLogger(__name__)


# Антиспам: окно последних таймстемпов на (bot_id, user_id)
_antispam: dict[tuple[int, int], deque[float]] = defaultdict(lambda: deque(maxlen=20))


def _bot_id_from_token(bot: Bot, bot_id_lookup: dict[str, int]) -> int | None:
    return bot_id_lookup.get(bot.token)


def _antispam_check(bot_id: int, user_id: int, limit: int) -> bool:
    if limit <= 0:
        return True
    now = time.time()
    q = _antispam[(bot_id, user_id)]
    cutoff = now - 60
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


async def _check_subscription(bot: Bot, channel: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status not in {"left", "kicked"}
    except TelegramAPIError:
        return False


async def _send_subscription_gate(bot: Bot, chat_id: int, child: ChildBot) -> None:
    if not child.subscribe_link:
        await bot.send_message(
            chat_id,
            f"{E_LOCK_CLOSED} Сначала подпишитесь на канал {child.subscribe_channel}.",
            parse_mode=ParseMode.HTML,
        )
        return
    kb = inline_kb([
        [inline_button("Подписаться", url=child.subscribe_link, icon=None)],
        [inline_button("Я подписался", callback_data="check_subscribe", icon=E_CHECK)],
    ])
    await bot.send_message(
        chat_id,
        f"<b>{E_LOCK_CLOSED} Доступ только для подписчиков канала</b>\n\n"
        f"Подпишитесь на {child.subscribe_channel} и нажмите «Я подписался».",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def _send_with_keyboard(
    bot: Bot, chat_id: int, text: str, keyboard_id: int | None
) -> None:
    inline_markup = None
    reply_markup = None
    if keyboard_id is not None:
        async with session_scope() as session:
            res = await session.execute(
                select(Keyboard)
                .where(Keyboard.id == keyboard_id)
                .options(selectinload(Keyboard.buttons))
            )
            kb = res.scalar_one_or_none()
        if kb is not None:
            if kb.kind == "inline":
                inline_markup = build_inline_from_db(kb)
            else:
                reply_markup = build_reply_from_db(kb)
    await bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=inline_markup or reply_markup,
    )


def make_router(bot_id: int) -> Router:
    """Создаёт роутер для конкретного дочернего бота (id из БД)."""
    router = Router(name=f"child.{bot_id}")

    @router.message(CommandStart())
    async def on_start(message: Message, bot: Bot) -> None:
        if message.from_user is None:
            return
        async with session_scope() as session:
            child = await get_bot_by_id(session, bot_id)
            if child is None or not child.is_active:
                return
            await upsert_child_user(
                session,
                bot_id=bot_id,
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
            text = child.start_text or "Привет!"
            kb_id = child.start_keyboard_id
            channel = child.subscribe_channel
            antispam = child.antispam_per_minute

        if not _antispam_check(bot_id, message.from_user.id, antispam):
            await message.answer(f"{E_CROSS} Слишком часто, подождите минуту.")
            return

        if channel:
            ok = await _check_subscription(bot, channel, message.from_user.id)
            if not ok:
                async with session_scope() as session:
                    child = await get_bot_by_id(session, bot_id)
                if child is not None:
                    await _send_subscription_gate(bot, message.chat.id, child)
                return
        await _send_with_keyboard(bot, message.chat.id, text, kb_id)

    @router.callback_query(F.data == "check_subscribe")
    async def on_check_sub(call: CallbackQuery, bot: Bot) -> None:
        if call.from_user is None or call.message is None:
            await call.answer()
            return
        async with session_scope() as session:
            child = await get_bot_by_id(session, bot_id)
        if child is None or not child.subscribe_channel:
            await call.answer("Гейт выключен")
            return
        ok = await _check_subscription(bot, child.subscribe_channel, call.from_user.id)
        if ok:
            await call.answer("Подписка подтверждена!", show_alert=False)
            await _send_with_keyboard(
                bot, call.message.chat.id, child.start_text or f"{E_PARTY} Добро пожаловать!", child.start_keyboard_id
            )
        else:
            await call.answer("Подписки нет — подпишитесь и попробуйте снова.", show_alert=True)

    @router.message(F.text.startswith("/"))
    async def on_command(message: Message, bot: Bot) -> None:
        if message.from_user is None or message.text is None:
            return
        text = message.text.strip()
        if not text.startswith("/"):
            return
        cmd = text.split()[0].lstrip("/").split("@")[0].lower()
        if not cmd or cmd == "start":
            return  # /start обрабатывается отдельно
        async with session_scope() as session:
            child = await get_bot_by_id(session, bot_id)
            if child is None or not child.is_active:
                return
            res = await session.execute(
                select(BotCommand).where(
                    BotCommand.bot_id == bot_id, BotCommand.command == cmd
                )
            )
            command = res.scalar_one_or_none()
            if command is None:
                return
            response = command.response_text
            kb_id = command.keyboard_id
            channel = child.subscribe_channel
            antispam = child.antispam_per_minute
            await upsert_child_user(
                session,
                bot_id=bot_id,
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
        if not _antispam_check(bot_id, message.from_user.id, antispam):
            return
        if channel:
            ok = await _check_subscription(bot, channel, message.from_user.id)
            if not ok:
                async with session_scope() as session:
                    child = await get_bot_by_id(session, bot_id)
                if child is not None:
                    await _send_subscription_gate(bot, message.chat.id, child)
                return
        await _send_with_keyboard(bot, message.chat.id, response, kb_id)

    @router.message(F.text)
    async def on_text(message: Message, bot: Bot) -> None:
        if message.from_user is None or message.text is None:
            return
        if message.text.startswith("/"):
            return
        async with session_scope() as session:
            child = await get_bot_by_id(session, bot_id)
            if child is None or not child.is_active:
                return
            res = await session.execute(
                select(BotTrigger).where(BotTrigger.bot_id == bot_id)
            )
            triggers = list(res.scalars().all())
            channel = child.subscribe_channel
            antispam = child.antispam_per_minute
            await upsert_child_user(
                session,
                bot_id=bot_id,
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )

        body = message.text or ""
        body_low = body.lower()
        match: BotTrigger | None = None
        for t in triggers:
            pat = t.pattern.lower()
            if t.match_type == "exact" and body_low == pat:
                match = t
                break
            if t.match_type == "startswith" and body_low.startswith(pat):
                match = t
                break
            if t.match_type == "contains" and pat in body_low:
                match = t
                break

        # Обработка нажатия reply-кнопки: payload текстовой кнопки в reply-кб
        # хранится в поле KeyboardButton.payload, а message.text == button.text.
        if match is None:
            from telegram_bot_constructor.db.models import KeyboardButton as KbBtn

            async with session_scope() as session:
                res = await session.execute(
                    select(KbBtn)
                    .join(Keyboard, KbBtn.keyboard_id == Keyboard.id)
                    .where(Keyboard.bot_id == bot_id, KbBtn.text == body)
                )
                btn = res.scalar_one_or_none()
                if btn is not None and btn.action == "reply" and btn.payload:
                    if not _antispam_check(bot_id, message.from_user.id, antispam):
                        return
                    if channel:
                        ok = await _check_subscription(bot, channel, message.from_user.id)
                        if not ok:
                            async with session_scope() as s2:
                                ch = await get_bot_by_id(s2, bot_id)
                            if ch is not None:
                                await _send_subscription_gate(bot, message.chat.id, ch)
                            return
                    await bot.send_message(
                        message.chat.id, btn.payload, parse_mode=ParseMode.HTML
                    )
            return

        if not _antispam_check(bot_id, message.from_user.id, antispam):
            return
        if channel:
            ok = await _check_subscription(bot, channel, message.from_user.id)
            if not ok:
                async with session_scope() as session:
                    child = await get_bot_by_id(session, bot_id)
                if child is not None:
                    await _send_subscription_gate(bot, message.chat.id, child)
                return

        kb_id = match.keyboard_id
        text_resp = match.response_text
        await _send_with_keyboard(bot, message.chat.id, text_resp, kb_id)

    @router.callback_query()
    async def on_callback(call: CallbackQuery, bot: Bot) -> None:
        # callback_data inline-кнопок: либо "btn:<id>" (по умолчанию), либо
        # пользовательская строка. Если найдём кнопку — ответим её payload-ом
        # для action="reply". Для action="callback" просто подтвердим.
        if call.data is None:
            await call.answer()
            return
        from telegram_bot_constructor.db.models import KeyboardButton as KbBtn

        if call.data.startswith("btn:"):
            try:
                btn_id = int(call.data.split(":", 1)[1])
            except ValueError:
                await call.answer()
                return
            async with session_scope() as session:
                res = await session.execute(
                    select(KbBtn)
                    .join(Keyboard, KbBtn.keyboard_id == Keyboard.id)
                    .where(KbBtn.id == btn_id, Keyboard.bot_id == bot_id)
                )
                btn = res.scalar_one_or_none()
            if btn is None:
                await call.answer()
                return
            if btn.action == "reply" and btn.payload and call.message is not None:
                await bot.send_message(call.message.chat.id, btn.payload, parse_mode=ParseMode.HTML)
            await call.answer()
            return
        # Пользовательский callback_data — попробуем найти кнопку по payload
        async with session_scope() as session:
            res = await session.execute(
                select(KbBtn)
                .join(Keyboard, KbBtn.keyboard_id == Keyboard.id)
                .where(Keyboard.bot_id == bot_id, KbBtn.payload == call.data)
            )
            btn = res.scalar_one_or_none()
        if btn and btn.action == "reply" and btn.payload and call.message is not None:
            await bot.send_message(call.message.chat.id, btn.payload, parse_mode=ParseMode.HTML)
        await call.answer()

    return router
