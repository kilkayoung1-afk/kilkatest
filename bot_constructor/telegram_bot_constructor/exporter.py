"""Экспорт дочернего бота в standalone-проект.

При нажатии на кнопку «Выгрузить код» в карточке бота родительский бот
собирает все настройки бота из БД (текст /start, команды, триггеры,
клавиатуры) и упаковывает их вместе с готовым ``bot.py`` в zip-архив.
Архив отправляется владельцу как документ в чат.

Загруженный архив содержит self-contained проект на ``aiogram 3.x`` —
запускается командой ``python bot.py`` после ``pip install -r requirements.txt``.
"""

from __future__ import annotations

import io
import json
import string
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from telegram_bot_constructor.db.models import ChildBot, Keyboard


async def _serialize_bot(session: AsyncSession, bot_id: int) -> dict:
    res = await session.execute(
        select(ChildBot)
        .where(ChildBot.id == bot_id)
        .options(
            selectinload(ChildBot.commands),
            selectinload(ChildBot.triggers),
            selectinload(ChildBot.keyboards).selectinload(Keyboard.buttons),
        )
    )
    bot: ChildBot | None = res.scalar_one_or_none()
    if bot is None:
        raise ValueError(f"bot {bot_id} not found")

    commands = [
        {
            "command": c.command,
            "description": c.description,
            "response_text": c.response_text,
            "keyboard_id": c.keyboard_id,
        }
        for c in bot.commands
    ]
    triggers = [
        {
            "match_type": t.match_type,
            "pattern": t.pattern,
            "response_text": t.response_text,
            "keyboard_id": t.keyboard_id,
        }
        for t in bot.triggers
    ]
    keyboards = []
    for kb in bot.keyboards:
        rows = defaultdict(list)
        for b in kb.buttons:
            rows[b.row].append(b)
        grid = []
        for row_idx in sorted(rows):
            row = sorted(rows[row_idx], key=lambda b: b.col)
            grid.append([
                {
                    "text": b.text,
                    "icon_custom_emoji_id": b.icon_custom_emoji_id,
                    "action": b.action,
                    "payload": b.payload,
                }
                for b in row
            ])
        keyboards.append({
            "id": kb.id,
            "kind": kb.kind,
            "title": kb.title,
            "resize": kb.resize,
            "one_time": kb.one_time,
            "buttons": grid,
        })
    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "title": bot.title,
        "username": bot.username,
        "start_text": bot.start_text or "Привет!",
        "subscribe_channel": bot.subscribe_channel,
        "subscribe_link": bot.subscribe_link,
        "antispam_per_minute": bot.antispam_per_minute,
        "commands": commands,
        "triggers": triggers,
        "keyboards": keyboards,
    }


# Шаблон bot.py — самодостаточный standalone-бот.
# Используется ``string.Template`` с ``$NAME``-плейсхолдерами, чтобы
# фигурные скобки в коде шаблона не интерпретировались как плейсхолдеры.
BOT_PY_TEMPLATE = string.Template('''"""Standalone Telegram-бот, выгруженный из конструктора.

Создано с помощью $CONSTRUCTOR_LINK.

Запуск:
    1. ``python -m venv .venv && source .venv/bin/activate``
    2. ``pip install -r requirements.txt``
    3. Скопировать ``.env.example`` в ``.env`` и вписать ``BOT_TOKEN``.
    4. ``python bot.py``
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton as TgKeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

CONFIG_PATH = Path(__file__).with_name("config.json")
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

CONSTRUCTOR_FOOTER = $CONSTRUCTOR_FOOTER_REPR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------- helpers --------------------------------------------------------


def _kb_by_id(kb_id):
    if kb_id is None:
        return None
    for kb in CONFIG.get("keyboards", []):
        if kb["id"] == kb_id:
            return kb
    return None


def _build_inline(kb):
    rows = []
    for row in kb.get("buttons", []):
        out_row = []
        for b in row:
            kwargs = {"text": b["text"]}
            if b.get("icon_custom_emoji_id"):
                kwargs["icon_custom_emoji_id"] = b["icon_custom_emoji_id"]
            if b["action"] == "url":
                kwargs["url"] = b.get("payload") or "https://t.me"
            else:
                kwargs["callback_data"] = b.get("payload") or "noop"
            out_row.append(InlineKeyboardButton(**kwargs))
        rows.append(out_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_reply(kb):
    rows = []
    for row in kb.get("buttons", []):
        out_row = []
        for b in row:
            kwargs = {"text": b["text"]}
            if b.get("icon_custom_emoji_id"):
                kwargs["icon_custom_emoji_id"] = b["icon_custom_emoji_id"]
            out_row.append(TgKeyboardButton(**kwargs))
        rows.append(out_row)
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=kb.get("resize", True),
        one_time_keyboard=kb.get("one_time", False),
    )


def _markup(kb_id):
    kb = _kb_by_id(kb_id)
    if kb is None:
        return None
    if kb["kind"] == "inline":
        return _build_inline(kb)
    return _build_reply(kb)


_antispam = defaultdict(lambda: deque(maxlen=20))


def _antispam_ok(user_id, limit):
    if limit <= 0:
        return True
    now = time.time()
    q = _antispam[user_id]
    cutoff = now - 60
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


async def _check_subscription(bot, channel, user_id):
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status not in {"left", "kicked"}
    except TelegramAPIError:
        return False


async def _gate_or_run(bot, message, action):
    user_id = message.from_user.id if message.from_user else 0
    if not _antispam_ok(user_id, CONFIG.get("antispam_per_minute", 0)):
        return
    channel = CONFIG.get("subscribe_channel")
    if channel:
        ok = await _check_subscription(bot, channel, user_id)
        if not ok:
            link = CONFIG.get("subscribe_link") or "https://t.me"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Подписаться", url=link)],
                [InlineKeyboardButton(text="Я подписался", callback_data="check_subscribe")],
            ])
            await message.answer(
                "Сначала подпишитесь на канал " + str(channel),
                reply_markup=kb,
            )
            return
    await action()


# ---------- handlers -------------------------------------------------------

router = Router()


def _start_text():
    base = CONFIG.get("start_text") or "Привет!"
    if CONSTRUCTOR_FOOTER:
        return base + "\\n\\n" + CONSTRUCTOR_FOOTER
    return base


@router.message(CommandStart())
async def on_start(message: Message, bot: Bot):
    async def go():
        # start не имеет настроенной keyboard в выгрузке (используется default text)
        await message.answer(_start_text(), parse_mode=ParseMode.HTML)
    await _gate_or_run(bot, message, go)


@router.callback_query(F.data == "check_subscribe")
async def on_check_subscribe(call: CallbackQuery, bot: Bot):
    if not call.from_user or not call.message:
        await call.answer()
        return
    channel = CONFIG.get("subscribe_channel")
    if not channel:
        await call.answer()
        return
    ok = await _check_subscription(bot, channel, call.from_user.id)
    if ok:
        await call.answer("Спасибо!")
        await call.message.answer(_start_text(), parse_mode=ParseMode.HTML)
    else:
        await call.answer("Подписки нет — попробуйте ещё раз", show_alert=True)


@router.message(F.text.startswith("/"))
async def on_command(message: Message, bot: Bot):
    if not message.text:
        return
    cmd = message.text.split()[0].lstrip("/").split("@")[0].lower()
    if not cmd or cmd == "start":
        return
    for c in CONFIG.get("commands", []):
        if c["command"] == cmd:
            async def go(c=c):
                await message.answer(
                    c["response_text"],
                    parse_mode=ParseMode.HTML,
                    reply_markup=_markup(c.get("keyboard_id")),
                )
            await _gate_or_run(bot, message, go)
            return


@router.message(F.text)
async def on_text(message: Message, bot: Bot):
    text = (message.text or "").lower()
    if text.startswith("/"):
        return
    for t in CONFIG.get("triggers", []):
        pat = t["pattern"].lower()
        match = (
            (t["match_type"] == "exact" and text == pat)
            or (t["match_type"] == "startswith" and text.startswith(pat))
            or (t["match_type"] == "contains" and pat in text)
        )
        if match:
            async def go(t=t):
                await message.answer(
                    t["response_text"],
                    parse_mode=ParseMode.HTML,
                    reply_markup=_markup(t.get("keyboard_id")),
                )
            await _gate_or_run(bot, message, go)
            return
    # reply-кнопки: если текст совпал с одной из reply-кнопок и у неё action=reply
    body = message.text or ""
    for kb in CONFIG.get("keyboards", []):
        for row in kb.get("buttons", []):
            for b in row:
                if b["text"] == body and b["action"] == "reply" and b.get("payload"):
                    payload = b["payload"]

                    async def go(payload=payload):
                        await message.answer(payload, parse_mode=ParseMode.HTML)

                    await _gate_or_run(bot, message, go)
                    return


@router.callback_query()
async def on_callback(call: CallbackQuery, bot: Bot):
    if not call.data:
        await call.answer()
        return
    for kb in CONFIG.get("keyboards", []):
        for row in kb.get("buttons", []):
            for b in row:
                if b.get("payload") == call.data and b["action"] == "reply" and b.get("payload"):
                    if call.message:
                        await call.message.answer(b["payload"], parse_mode=ParseMode.HTML)
                    await call.answer()
                    return
    await call.answer()


# ---------- entry ----------------------------------------------------------


async def main():
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан в .env")
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    logger.info("Starting standalone bot (built with constructor)")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
''')


REQUIREMENTS_TXT = """aiogram==3.13.1
python-dotenv==1.0.1
"""

ENV_EXAMPLE = """# Токен бота от @BotFather
BOT_TOKEN=
"""

README_TEMPLATE = string.Template("""# $TITLE

Standalone Telegram-бот, выгруженный из $CONSTRUCTOR_NAME_LINK.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # вписать BOT_TOKEN
python bot.py
```

## Что внутри

- `bot.py` — основной код на `aiogram 3.x` (читает `config.json`).
- `config.json` — все настройки бота: текст /start, команды, триггеры, клавиатуры с premium-эмодзи.
- `requirements.txt` — зависимости.
- `.env.example` — шаблон переменных окружения.

## Как править поведение

- Меняй ответы и команды прямо в `config.json`.
- Меняй обработчики/логику — в `bot.py`.
- Premium-эмодзи на кнопках — поле `icon_custom_emoji_id` в `config.json`.
""")


def _python_repr(value: str | None) -> str:
    """Безопасное repr для подстановки в шаблон bot.py."""
    if value is None:
        return "None"
    return repr(value)


async def build_export_zip(
    session: AsyncSession,
    bot_id: int,
    *,
    constructor_username: str | None,
    constructor_title: str | None,
) -> bytes:
    """Собирает zip с standalone-кодом для дочернего бота."""
    config = await _serialize_bot(session, bot_id)
    title = config["title"] or config["username"] or f"bot_{bot_id}"

    if constructor_username:
        link = f"@{constructor_username}"
    elif constructor_title:
        link = constructor_title
    else:
        link = "конструктора ботов"

    # premium-эмодзи «Бот» (см. emoji.py: E_ROBOT)
    bot_premium = '<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji>'
    footer = f'<i>{bot_premium} Создано с помощью {link}</i>' if link else ""

    bot_py = BOT_PY_TEMPLATE.substitute(
        CONSTRUCTOR_LINK=link,
        CONSTRUCTOR_FOOTER_REPR=_python_repr(footer),
    )

    readme = README_TEMPLATE.substitute(
        TITLE=title,
        CONSTRUCTOR_NAME_LINK=link,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_safe_name(title)}/bot.py", bot_py)
        zf.writestr(
            f"{_safe_name(title)}/config.json",
            json.dumps(config, ensure_ascii=False, indent=2),
        )
        zf.writestr(f"{_safe_name(title)}/requirements.txt", REQUIREMENTS_TXT)
        zf.writestr(f"{_safe_name(title)}/.env.example", ENV_EXAMPLE)
        zf.writestr(f"{_safe_name(title)}/README.md", readme)
    return buf.getvalue()


def _safe_name(name: str) -> str:
    """Безопасное имя папки внутри архива."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    safe = safe.strip("_") or "bot"
    return safe[:48]


def _default_config(*, title: str | None, username: str | None) -> dict:
    """Минимальный config.json для шаблонного бота без правок."""
    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "username": username,
        "start_text": (
            "<b>Привет!</b>\n\n"
            "Это твой бот, собранный из шаблона. "
            "Меняй ответы и команды в <code>config.json</code>, "
            "логику — в <code>bot.py</code>."
        ),
        "subscribe_channel": None,
        "subscribe_link": None,
        "antispam_per_minute": 0,
        "commands": [
            {
                "command": "help",
                "description": "Справка",
                "response_text": (
                    "<b>Справка</b>\n\n"
                    "Этот бот использует premium-эмодзи через "
                    "<code>icon_custom_emoji_id</code> и "
                    "<code>&lt;tg-emoji&gt;</code>."
                ),
                "keyboard_id": None,
            },
        ],
        "triggers": [],
        "keyboards": [],
    }


def build_starter_zip(
    *,
    token: str,
    bot_username: str | None,
    bot_title: str | None,
    constructor_username: str | None,
    constructor_title: str | None,
) -> bytes:
    """Собирает standalone-zip по одному только токену (без участия БД).

    Используется в пункте меню «Получить код по токену»: пользователь
    присылает токен, конструктор валидирует его через ``getMe`` и отдаёт
    готовый архив с предзаполненным ``BOT_TOKEN`` в ``.env``.
    """
    if constructor_username:
        link = f"@{constructor_username}"
    elif constructor_title:
        link = constructor_title
    else:
        link = "конструктора ботов"

    bot_premium = '<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji>'
    footer = f'<i>{bot_premium} Создано с помощью {link}</i>' if link else ""

    bot_py = BOT_PY_TEMPLATE.substitute(
        CONSTRUCTOR_LINK=link,
        CONSTRUCTOR_FOOTER_REPR=_python_repr(footer),
    )
    title = bot_title or bot_username or "bot"
    readme = README_TEMPLATE.substitute(TITLE=title, CONSTRUCTOR_NAME_LINK=link)
    config = _default_config(title=bot_title, username=bot_username)
    env_filled = "# Токен бота от @BotFather\nBOT_TOKEN=" + token + "\n"

    folder = _safe_name(title)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{folder}/bot.py", bot_py)
        zf.writestr(
            f"{folder}/config.json",
            json.dumps(config, ensure_ascii=False, indent=2),
        )
        zf.writestr(f"{folder}/requirements.txt", REQUIREMENTS_TXT)
        zf.writestr(f"{folder}/.env", env_filled)
        zf.writestr(f"{folder}/.env.example", ENV_EXAMPLE)
        zf.writestr(f"{folder}/README.md", readme)
    return buf.getvalue()
