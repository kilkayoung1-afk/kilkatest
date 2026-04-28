# meta developer: @Kilka_Young
# description: Telegram randomizer bot (aiogram 3.x)
# requires: aiogram>=3.0

import asyncio
import logging
import os
import random
import re

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ---------- Premium emoji IDs ----------
EMOJI_BOT = ("🤖", "6030400221232501136")
EMOJI_SETTINGS = ("⚙", "5870982283724328568")
EMOJI_STATS = ("📊", "5870921681735781843")
EMOJI_GROWTH = ("📊", "5870930636742595124")
EMOJI_GIFT = ("🎁", "6032644646587338669")
EMOJI_PARTY = ("🎉", "6041731551845159060")
EMOJI_CHECK = ("✅", "5870633910337015697")
EMOJI_CROSS = ("❌", "5870657884844462243")
EMOJI_PENCIL = ("🖋", "5870676941614354370")
EMOJI_INFO = ("ℹ", "6028435952299413210")
EMOJI_COIN = ("🪙", "5904462880941545555")
EMOJI_LINK = ("🔗", "5769289093221454192")
EMOJI_MEGAPHONE = ("📣", "6039422865189638057")
EMOJI_LOADING = ("🔄", "5345906554510012647")
EMOJI_DOWN = ("📰", "5893057118545646106")
EMOJI_ADDTEXT = ("🔡", "5771851822897566479")
EMOJI_FONT = ("🔗", "5870801517140775623")
EMOJI_TAG = ("🏷", "5886285355279193209")
EMOJI_CLOCK = ("⏰", "5983150113483134607")
EMOJI_SMILE = ("🙂", "5870764288364252592")


def pe(pair: tuple[str, str]) -> str:
    """Render a premium tg-emoji tag for messages."""
    emoji, emoji_id = pair
    return f'<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji>'


# ---------- FSM states ----------
class RandomStates(StatesGroup):
    waiting_range = State()
    waiting_choice = State()
    waiting_shuffle = State()


# ---------- Keyboards ----------
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Случайное число",
                    callback_data="rand_number",
                    icon_custom_emoji_id=EMOJI_STATS[1],
                )
            ],
            [
                InlineKeyboardButton(
                    text="Выбор из списка",
                    callback_data="rand_choice",
                    icon_custom_emoji_id=EMOJI_ADDTEXT[1],
                )
            ],
            [
                InlineKeyboardButton(
                    text="Бросить кубик",
                    callback_data="rand_dice",
                    icon_custom_emoji_id=EMOJI_GIFT[1],
                ),
                InlineKeyboardButton(
                    text="Монетка",
                    callback_data="rand_coin",
                    icon_custom_emoji_id=EMOJI_COIN[1],
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Перемешать список",
                    callback_data="rand_shuffle",
                    icon_custom_emoji_id=EMOJI_LOADING[1],
                )
            ],
            [
                InlineKeyboardButton(
                    text="О боте",
                    callback_data="about",
                    icon_custom_emoji_id=EMOJI_INFO[1],
                )
            ],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◁ Назад",
                    callback_data="back_menu",
                )
            ]
        ]
    )


def result_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ещё раз",
                    callback_data=f"again:{action}",
                    icon_custom_emoji_id=EMOJI_LOADING[1],
                )
            ],
            [
                InlineKeyboardButton(
                    text="◁ Назад",
                    callback_data="back_menu",
                )
            ],
        ]
    )


# ---------- Texts ----------
def start_text(user_name: str) -> str:
    return (
        f"<b>{pe(EMOJI_BOT)} Привет, {user_name}!</b>\n\n"
        f"{pe(EMOJI_PARTY)} Я — бот-рандомайзер. Помогу сделать случайный выбор.\n\n"
        f"<b>{pe(EMOJI_SETTINGS)} Возможности:</b>\n"
        f"  {pe(EMOJI_STATS)} Случайное число в диапазоне\n"
        f"  {pe(EMOJI_ADDTEXT)} Случайный выбор из списка\n"
        f"  {pe(EMOJI_GIFT)} Бросок кубика (1–6)\n"
        f"  {pe(EMOJI_COIN)} Подбросить монетку\n"
        f"  {pe(EMOJI_LOADING)} Перемешать список\n\n"
        f"<i>Выберите действие ниже {pe(EMOJI_DOWN)}</i>"
    )


ABOUT_TEXT = (
    f"<b>{pe(EMOJI_INFO)} О боте</b>\n\n"
    f"{pe(EMOJI_BOT)} Простой бот-рандомайзер на <b>aiogram 3.x</b>.\n"
    f"{pe(EMOJI_PENCIL)} Один файл, без базы данных.\n"
    f"{pe(EMOJI_CLOCK)} Использует <code>random.SystemRandom</code> для генерации.\n\n"
    f"<i>Разработчик: @Kilka_Young</i>"
)


RANGE_PROMPT = (
    f"<b>{pe(EMOJI_STATS)} Случайное число</b>\n\n"
    f"{pe(EMOJI_PENCIL)} Отправь диапазон в формате:\n"
    f"<code>1 100</code>   или   <code>1-100</code>\n\n"
    f"<i>Максимум: от -10^9 до 10^9</i>"
)

CHOICE_PROMPT = (
    f"<b>{pe(EMOJI_ADDTEXT)} Выбор из списка</b>\n\n"
    f"{pe(EMOJI_PENCIL)} Отправь варианты, разделённые запятыми или с новой строки.\n\n"
    f"<i>Пример:</i> <code>Петя, Вася, Маша, Коля</code>"
)

SHUFFLE_PROMPT = (
    f"<b>{pe(EMOJI_LOADING)} Перемешать список</b>\n\n"
    f"{pe(EMOJI_PENCIL)} Отправь варианты, разделённые запятыми или с новой строки."
)


# ---------- Bot & Dispatcher ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("randomizer_bot")

dp = Dispatcher(storage=MemoryStorage())
rng = random.SystemRandom()

MAX_RANGE = 10**9
MAX_ITEMS = 200
MAX_ITEM_LEN = 100


def parse_items(text: str) -> list[str]:
    raw = re.split(r"[,\n]+", text)
    items = [x.strip() for x in raw if x.strip()]
    items = [x[:MAX_ITEM_LEN] for x in items]
    return items[:MAX_ITEMS]


# ---------- Handlers ----------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        start_text(message.from_user.first_name or "друг"),
        reply_markup=main_menu_kb(),
    )


@dp.callback_query(F.data == "back_menu")
async def cb_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        start_text(callback.from_user.first_name or "друг"),
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery) -> None:
    await callback.message.edit_text(ABOUT_TEXT, reply_markup=back_kb())
    await callback.answer()


@dp.callback_query(F.data == "rand_number")
async def cb_rand_number(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RandomStates.waiting_range)
    await callback.message.edit_text(RANGE_PROMPT, reply_markup=back_kb())
    await callback.answer()


@dp.callback_query(F.data == "rand_choice")
async def cb_rand_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RandomStates.waiting_choice)
    await callback.message.edit_text(CHOICE_PROMPT, reply_markup=back_kb())
    await callback.answer()


@dp.callback_query(F.data == "rand_shuffle")
async def cb_rand_shuffle(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RandomStates.waiting_shuffle)
    await callback.message.edit_text(SHUFFLE_PROMPT, reply_markup=back_kb())
    await callback.answer()


@dp.callback_query(F.data == "rand_dice")
async def cb_rand_dice(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    value = rng.randint(1, 6)
    text = (
        f"<b>{pe(EMOJI_GIFT)} Кубик брошен!</b>\n\n"
        f"{pe(EMOJI_STATS)} Результат: <b>{value}</b>"
    )
    await callback.message.edit_text(text, reply_markup=result_kb("dice"))
    await callback.answer()


@dp.callback_query(F.data == "rand_coin")
async def cb_rand_coin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    side = rng.choice(["Орёл", "Решка"])
    text = (
        f"<b>{pe(EMOJI_COIN)} Монетка брошена!</b>\n\n"
        f"{pe(EMOJI_CHECK)} Выпало: <b>{side}</b>"
    )
    await callback.message.edit_text(text, reply_markup=result_kb("coin"))
    await callback.answer()


@dp.callback_query(F.data.startswith("again:"))
async def cb_again(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "dice":
        await cb_rand_dice(callback, state)
    elif action == "coin":
        await cb_rand_coin(callback, state)
    else:
        await callback.answer()


@dp.message(RandomStates.waiting_range)
async def on_range(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    match = re.match(r"^\s*(-?\d+)\s*[-\s,]+\s*(-?\d+)\s*$", text)
    if not match:
        await message.answer(
            f"<b>{pe(EMOJI_CROSS)} Неверный формат.</b>\n"
            f"{pe(EMOJI_INFO)} Пример: <code>1 100</code> или <code>1-100</code>",
            reply_markup=back_kb(),
        )
        return
    a, b = int(match.group(1)), int(match.group(2))
    if abs(a) > MAX_RANGE or abs(b) > MAX_RANGE:
        await message.answer(
            f"<b>{pe(EMOJI_CROSS)} Числа слишком большие.</b>\n"
            f"{pe(EMOJI_INFO)} Максимум: ±{MAX_RANGE:,}".replace(",", " "),
            reply_markup=back_kb(),
        )
        return
    lo, hi = (a, b) if a <= b else (b, a)
    value = rng.randint(lo, hi)
    await state.clear()
    await message.answer(
        f"<b>{pe(EMOJI_STATS)} Случайное число</b>\n\n"
        f"{pe(EMOJI_PENCIL)} Диапазон: <code>[{lo}; {hi}]</code>\n"
        f"{pe(EMOJI_CHECK)} Результат: <b>{value}</b>",
        reply_markup=main_menu_kb(),
    )


@dp.message(RandomStates.waiting_choice)
async def on_choice(message: Message, state: FSMContext) -> None:
    items = parse_items(message.text or "")
    if len(items) < 2:
        await message.answer(
            f"<b>{pe(EMOJI_CROSS)} Нужно минимум 2 варианта.</b>\n"
            f"{pe(EMOJI_INFO)} Разделяй запятыми или новой строкой.",
            reply_markup=back_kb(),
        )
        return
    choice = rng.choice(items)
    preview = "\n".join(f"  • <code>{x}</code>" for x in items[:10])
    if len(items) > 10:
        preview += f"\n  <i>…и ещё {len(items) - 10}</i>"
    await state.clear()
    await message.answer(
        f"<b>{pe(EMOJI_ADDTEXT)} Выбор из списка</b>\n\n"
        f"{pe(EMOJI_PENCIL)} Варианты ({len(items)}):\n{preview}\n\n"
        f"{pe(EMOJI_PARTY)} Выбрано: <b>{choice}</b>",
        reply_markup=main_menu_kb(),
    )


@dp.message(RandomStates.waiting_shuffle)
async def on_shuffle(message: Message, state: FSMContext) -> None:
    items = parse_items(message.text or "")
    if len(items) < 2:
        await message.answer(
            f"<b>{pe(EMOJI_CROSS)} Нужно минимум 2 элемента.</b>\n"
            f"{pe(EMOJI_INFO)} Разделяй запятыми или новой строкой.",
            reply_markup=back_kb(),
        )
        return
    shuffled = items[:]
    rng.shuffle(shuffled)
    numbered = "\n".join(f"  <b>{i}.</b> <code>{x}</code>" for i, x in enumerate(shuffled, 1))
    await state.clear()
    await message.answer(
        f"<b>{pe(EMOJI_LOADING)} Список перемешан</b>\n\n{numbered}",
        reply_markup=main_menu_kb(),
    )


@dp.message()
async def fallback(message: Message) -> None:
    await message.answer(
        f"<b>{pe(EMOJI_INFO)} Используй /start для открытия меню.</b>",
        reply_markup=main_menu_kb(),
    )


# ---------- Entry point ----------
async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not set. Export it before running: export BOT_TOKEN=123:ABC"
        )
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    logger.info("Starting randomizer bot…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
