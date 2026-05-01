"""/start handler, reply-keyboard text handlers, help/status/policy."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bothost import emoji as e
from bothost.config import Config
from bothost.db import Database
from bothost.keyboards import (
    KBD_BUY,
    KBD_HELP,
    KBD_STATUS,
    KBD_TERMS,
    KBD_UPLOAD,
    cancel_keyboard,
    plans_menu,
    reply_keyboard,
    status_lines,
)
from bothost.states import UploadBot

router = Router(name="start")


WELCOME = (
    f"{e.SMILE} Привет! Это <b>bothost</b> — сервис, который запускает твоих Python-ботов.\n\n"
    f"Как это работает:\n"
    f"{e.COIN} Покупаешь подписку (от <b>50⭐ за 14 дней</b>).\n"
    f"{e.PAPERCLIP} Присылаешь <b>.py</b> файл или <b>.zip</b> архив с проектом — я попрошу имя и запущу.\n"
    f"{e.BOT} Можешь держать сразу несколько ботов (по тарифу).\n\n"
    f"Управляй ботом кнопками снизу 👇"
)


PLANS_HEADER = f"{e.COIN} <b>Тарифы</b> — выбери план:"

HELP = (
    f"{e.INFO} <b>Подробнее</b>\n\n"
    f"{e.BOX} <b>Изоляция:</b> бот работает в Docker (256 МБ RAM, 0.5 CPU), без root, "
    f"без доступа к хосту. Сеть ограничена.\n"
    f"{e.LOCK_CLOSED} <b>Защита:</b> блокирую коды-стиллеры (попытки читать SSH-ключи, AWS/crypto-кошельки, "
    f"браузерные профили, /etc/shadow и т.п.).\n"
    f"{e.PAPERCLIP} <b>Что можно загружать:</b>\n"
    f"  • Один файл <code>bot.py</code> до 1 МБ.\n"
    f"  • <b>ZIP-архив</b> до 5 МБ (распакованный — до 20 МБ, до 100 файлов). "
    f"В корне обязателен <code>bot.py</code>. Можно положить <code>requirements.txt</code> "
    f"(до 50 пакетов) — установлю в <code>/app/data/site-packages</code>, "
    f"git+/file:/-зависимости запрещены.\n"
    f"{e.FILE} <b>Запись на диск:</b> только в <code>/app/data</code> "
    f"(сохраняется между перезапусками). <code>/app</code> — read-only.\n"
    f"{e.CODE} <b>Уже предустановлено:</b> aiogram, pyTelegramBotAPI, python-telegram-bot, "
    f"telethon, requests, aiohttp, httpx, sqlalchemy, asyncpg, redis, pymongo/motor, "
    f"pydantic, openai, anthropic, fastapi, pillow, lxml/bs4, и ещё ~50 популярных.\n"
    f"{e.PENCIL} <b>Имя бота:</b> <code>[A-Za-z0-9_-]</code>, до 32 символов.\n\n"
    f"{e.CROSS} Размещай только свой код. За поведение бота отвечает его автор. "
    f"Подробности — <code>/terms</code> и <code>/privacy</code>."
)


TERMS = (
    f"{e.LOCK_CLOSED} <b>Условия использования</b>\n\n"
    f"{e.BOT} <b>Сервис.</b> Я — bothost, технический оператор. Я предоставляю инфраструктуру "
    f"(изолированный Docker-контейнер) для запуска <i>твоего</i> Telegram-бота на Python. "
    f"Я не являюсь автором ботов, размещённых пользователями, и не несу ответственности "
    f"за их содержание и поведение.\n\n"
    f"{e.PAPERCLIP} <b>Что разрешено.</b> Запускать только <i>собственный</i> код Python, "
    f"не нарушающий законы РФ и ToS Telegram (<code>https://telegram.org/tos</code>). "
    f"Допустимы любые легальные боты: каналы, услуги, мини-игры, утилиты.\n\n"
    f"{e.CROSS} <b>Что запрещено.</b>\n"
    f"  • Спам, фишинг, скам, дидосы, ботнеты.\n"
    f"  • Кража данных (стиллеры): чтение чужих ключей/кошельков/токенов.\n"
    f"  • CSAM и контент 18+ без подтверждения возраста.\n"
    f"  • Майнинг криптовалют, отмыв звёзд.\n"
    f"  • Любые нарушения Telegram ToS и российского законодательства.\n"
    f"  Нарушения = немедленная блокировка без возврата средств. Стиллеры режутся ещё на этапе загрузки кода.\n\n"
    f"{e.COIN} <b>Оплата и сроки.</b> Подписка покупается за Telegram Stars (<code>XTR</code>). "
    f"Срок — 14 дней с момента оплаты, продлевается покупкой нового тарифа. "
    f"После истечения срока боты автоматически останавливаются. Файлы сохраняются ещё 7 дней — "
    f"можно продлить и продолжить с того же места.\n\n"
    f"{e.CALENDAR} <b>Возврат средств.</b> Telegram Stars не подлежат возврату по правилам Telegram, "
    f"кроме случая, когда сервис не предоставил оплаченную услугу по моей вине "
    f"(например, бот не смог запуститься из-за моей ошибки в течение 24 часов после оплаты, "
    f"и проблема не решилась). В таком случае напиши админу — оформим возврат через Telegram refund API.\n\n"
    f"{e.LOCK_OPEN} <b>Ограничение ответственности.</b> Сервис предоставляется «как есть». "
    f"Я не гарантирую 100%-ный аптайм и не несу ответственности за упущенную выгоду, "
    f"потерю данных в /app/data при сбоях, или за действия твоего бота по отношению к третьим лицам.\n\n"
    f"{e.MEGAPHONE} <b>Изменения.</b> Условия могут меняться. О существенных изменениях я уведомлю в боте за 7 дней.\n\n"
    f"{e.PERSON_OK} <b>Контакт.</b> Админ: <code>tg://user?id=7119847306</code>. "
    f"Конфиденциальность — <code>/privacy</code>."
)


PRIVACY = (
    f"{e.EYE} <b>Политика конфиденциальности</b>\n\n"
    f"{e.PROFILE} <b>Что я храню.</b>\n"
    f"  • Твой Telegram <b>ID</b> и <b>username</b> (для авторизации и связи).\n"
    f"  • <b>Подписку</b>: тариф, срок, лимит ботов, сумма звёзд, ID платежа.\n"
    f"  • <b>Метаданные ботов</b>: имя, статус, ID контейнера, время запуска.\n"
    f"  • <b>Код бота</b>, который ты загрузил, и его файлы из <code>/app/data</code> — на диске сервера.\n"
    f"  • <b>Логи</b> работы бота за последние 1000 строк (для команды «Логи»).\n\n"
    f"{e.LOCK_CLOSED} <b>Что я НЕ собираю.</b>\n"
    f"  • Содержимое чатов твоего бота с его пользователями — оно не проходит через bothost.\n"
    f"  • Данные банковских карт — оплата идёт через Telegram Stars, я вижу только сумму и ID транзакции.\n\n"
    f"{e.PEOPLE} <b>Кому я передаю данные.</b> Никому. Сторонним сервисам — нет. "
    f"Исключения: по обязательному запросу госорганов РФ; платёжные ID — Telegram (для возвратов).\n\n"
    f"{e.TRASH} <b>Удаление.</b> Команда <code>/delete_account</code> или сообщение админу — "
    f"и в течение 7 дней я уберу твой аккаунт, все боты, файлы и историю покупок. Бэкапы стираются ежемесячно.\n\n"
    f"{e.LOCK_OPEN} <b>Безопасность.</b> Данные хранятся на сервере оператора в SQLite. "
    f"Доступ к серверу есть только у админа. Каждый пользовательский бот изолирован Docker-контейнером "
    f"(uid 65534, cap-drop ALL, read-only fs, ulimits) — другие боты не могут читать твои файлы.\n\n"
    f"{e.PERSON_OK} <b>Права субъекта данных (152-ФЗ).</b> Можешь запросить копию своих данных, "
    f"исправить их или потребовать удаления — пиши админу <code>tg://user?id=7119847306</code>."
)


async def _show_status(target: Message, cfg: Config, db: Database, tg_id: int) -> None:
    sub = await db.get_subscription(tg_id)
    bots = await db.list_bots_for_user(tg_id)
    text = WELCOME + "\n\n" + status_lines(sub, bots)
    await target.answer(text, reply_markup=reply_keyboard())


async def _prompt_upload(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        f"{e.PAPERCLIP} Пришли <b>.py файл</b> (до 1 МБ) "
        f"или <b>.zip архив</b> (до 5 МБ) с <code>bot.py</code> в корне.\n\n"
        f"В архив можно положить <code>requirements.txt</code> — установлю зависимости.",
        reply_markup=cancel_keyboard(),
    )


# /start is the only slash command for end users (Telegram requires it for bot
# entry). Everything else goes through the persistent reply keyboard below.


@router.message(CommandStart())
async def handle_start(message: Message, cfg: Config, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.upsert_user(tg_id=user.id, username=user.username)
    await _show_status(message, cfg, db, user.id)


# --- reply-keyboard text handlers --------------------------------------------


@router.message(F.text == KBD_STATUS)
async def kbd_status(message: Message, cfg: Config, db: Database, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    await _show_status(message, cfg, db, message.from_user.id)


@router.message(F.text == KBD_HELP)
async def kbd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HELP, reply_markup=reply_keyboard())


@router.message(F.text == KBD_TERMS)
async def kbd_terms(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(TERMS, disable_web_page_preview=True)
    await message.answer(PRIVACY, disable_web_page_preview=True, reply_markup=reply_keyboard())


@router.message(F.text == KBD_BUY)
async def kbd_buy(message: Message, cfg: Config, state: FSMContext) -> None:
    await state.clear()
    await message.answer(PLANS_HEADER, reply_markup=plans_menu(cfg.plans))


@router.message(F.text == KBD_UPLOAD)
async def kbd_upload(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    # only allow upload if user is not already in the middle of an FSM flow
    current = await state.get_state()
    if current == UploadBot.waiting_for_name.state:
        await message.answer(
            f"{e.INFO} Сначала пришли имя для предыдущего бота — или нажми «Отмена»."
        )
        return
    await _prompt_upload(message, state)


# KBD_BOTS handler is in handlers/manage.py (depends on _show_bots_list).


# --- inline-callback handlers -------------------------------------------------


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery) -> None:
    if isinstance(call.message, Message):
        await call.message.answer(HELP)
    await call.answer()


@router.callback_query(F.data == "terms")
async def cb_terms(call: CallbackQuery) -> None:
    if isinstance(call.message, Message):
        await call.message.answer(TERMS, disable_web_page_preview=True)
        await call.message.answer(PRIVACY, disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, cfg: Config, db: Database, state: FSMContext) -> None:
    if call.from_user is None or not isinstance(call.message, Message):
        await call.answer()
        return
    await state.clear()
    await _show_status(call.message, cfg, db, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "status")
async def cb_status(call: CallbackQuery, cfg: Config, db: Database) -> None:
    if call.from_user is None or not isinstance(call.message, Message):
        await call.answer()
        return
    await _show_status(call.message, cfg, db, call.from_user.id)
    await call.answer()
