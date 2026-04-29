# Telegram Bot Constructor

Бесплатный конструктор Telegram-ботов с поддержкой **premium-эмодзи**
во всех сообщениях, inline- и reply-клавиатурах. Написан на
[`aiogram 3.x`](https://docs.aiogram.dev/) + SQLite.

## Возможности

- Добавление любого количества дочерних ботов по токену от @BotFather.
- Все дочерние боты крутятся **в одном процессе** через `asyncio` —
  никакой внешней инфраструктуры (Docker, Kubernetes, Redis) не нужно.
- Конструктор сообщений `/start` с HTML-форматированием и premium-эмодзи.
- Произвольные команды (`/help`, `/info` и т.п.) — каждая со своим ответом.
- Текстовые триггеры: реакция по `exact` / `contains` / `startswith`.
- Inline-клавиатуры с premium-эмодзи на иконках кнопок (`icon_custom_emoji_id`).
- Reply-клавиатуры с premium-эмодзи.
- Подписочный гейт (требовать подписку на канал).
- Простой антиспам (N сообщений / минута).
- Рассылка по пользователям дочернего бота.
- Статистика по каждому боту + админ-панель для владельца сервиса.

## Premium-эмодзи

Каталог premium-эмодзи лежит в [`telegram_bot_constructor/emoji.py`](telegram_bot_constructor/emoji.py).
Используются:

- В тексте: `<tg-emoji emoji-id="...">FALLBACK</tg-emoji>` (HTML).
- В inline-кнопках: поле `icon_custom_emoji_id`.
- В reply-кнопках: поле `icon_custom_emoji_id`.

```python
from telegram_bot_constructor.emoji import E_SETTINGS, E_CHECK
from telegram_bot_constructor.keyboards import inline_button, inline_kb

kb = inline_kb([
    [inline_button("Подписаться", url="https://t.me/...", icon=E_CHECK)],
    [inline_button("Настройки",   callback_data="settings", icon=E_SETTINGS)],
])

text = f"<b>{E_SETTINGS} Настройки</b>\nВыберите раздел."
```

## Быстрый старт

1. Создайте основного («родительского») бота у [@BotFather](https://t.me/BotFather)
   и скопируйте его токен.
2. Склонируйте репозиторий и установите зависимости:

   ```bash
   git clone https://github.com/kilkayoung1-afk/telegram-bot-constructor.git
   cd telegram-bot-constructor
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN` (и опционально `ADMIN_IDS`).
4. Запустите конструктор:

   ```bash
   python -m telegram_bot_constructor.main
   ```

5. Откройте своего бота в Telegram, нажмите `/start`, добавьте дочернего бота
   через меню «Добавить бота» и пришлите его токен. Дочерний бот сразу
   запустится и начнёт принимать сообщения.

## Архитектура

```
parent (родительский бот)        ─ aiogram Dispatcher (parent-polling)
   ├── /start, меню, FSM
   ├── editor (команды, триггеры, /start)
   ├── keyboards (inline / reply)
   ├── broadcast / stats / sub-gate
   └── admin

child runtime (пул дочерних)     ─ asyncio.create_task(start_polling) на каждого бота
   └── make_router(bot_id)       ─ читает конфиг бота из БД на каждое событие

storage                          ─ SQLite через SQLAlchemy[asyncio] + aiosqlite
```

При старте `main.py` поднимает родительский бот и автоматически запускает
все активные дочерние боты. При добавлении / удалении / включении /
выключении бот стартует или останавливается без рестарта процесса.

## Структура

```
telegram_bot_constructor/
├── main.py                 — точка входа
├── config.py               — настройки (.env)
├── emoji.py                — каталог premium-эмодзи
├── keyboards.py            — хелперы клавиатур с icon_custom_emoji_id
├── db/
│   ├── models.py           — SQLAlchemy ORM (User, ChildBot, Keyboards, ...)
│   ├── session.py          — async engine / session
│   └── repo.py             — data access
├── parent/
│   ├── dispatcher.py       — сборка роутеров
│   ├── menu.py             — главное меню и карточки
│   ├── states.py           — FSM
│   └── handlers/
│       ├── start.py        — /start и помощь
│       ├── bots.py         — список / добавление / карточка бота
│       ├── editor.py       — команды, триггеры, /start
│       ├── keyboards.py    — конструктор клавиатур
│       ├── broadcast.py    — рассылка
│       ├── stats.py        — статистика и подписочный гейт
│       └── admin.py        — админ-панель
└── child/
    ├── runtime.py          — пул polling-ов дочерних ботов
    └── handlers.py         — динамические хендлеры (читают БД)
```

## Лицензия

MIT.
