"""Keyboards used across the parent bot — both inline and reply.

Button icons use `icon_custom_emoji_id` (Bot API 9.4+) — Premium users see
animated custom emoji, others see plain text. Buttons therefore should NOT
carry plain Unicode emojis in their `text` field.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bothost.db import BotRecord, Subscription
from bothost.emoji import ID
from bothost.plans import Plan

# --- reply (persistent bottom) keyboard ---------------------------------------

# button labels — referenced by F.text matchers in handlers
KBD_UPLOAD = "Загрузить"
KBD_BOTS = "Мои боты"
KBD_BUY = "Купить"
KBD_STATUS = "Подписка"
KBD_HELP = "Помощь"
KBD_TERMS = "Политика"

KBD_ALL = {KBD_UPLOAD, KBD_BOTS, KBD_BUY, KBD_STATUS, KBD_HELP, KBD_TERMS}


def reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=KBD_UPLOAD, icon_custom_emoji_id=ID.SEND),
                KeyboardButton(text=KBD_BOTS, icon_custom_emoji_id=ID.BOT),
            ],
            [
                KeyboardButton(text=KBD_BUY, icon_custom_emoji_id=ID.COIN),
                KeyboardButton(text=KBD_STATUS, icon_custom_emoji_id=ID.STATS),
            ],
            [
                KeyboardButton(text=KBD_HELP, icon_custom_emoji_id=ID.INFO),
                KeyboardButton(text=KBD_TERMS, icon_custom_emoji_id=ID.LOCK_CLOSED),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# --- inline (per-message) keyboards -------------------------------------------


def plans_menu(plans: list[Plan]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plan in plans:
        rows.append(
            [
                InlineKeyboardButton(
                    text=plan.label(),
                    callback_data=f"buy:{plan.id}",
                    icon_custom_emoji_id=ID.COIN_SEND,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="menu",
                icon_custom_emoji_id=ID.DOWN,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bots_list_menu(records: list[BotRecord]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    icon_by_status = {
        "running": ID.CHECK,
        "stopped": ID.LOCK_CLOSED,
        "crashed": ID.CROSS,
        "expired": ID.CLOCK,
    }
    for r in records:
        rows.append(
            [
                InlineKeyboardButton(
                    text=r.name,
                    callback_data=f"bot:{r.id}",
                    icon_custom_emoji_id=icon_by_status.get(r.status, ID.LOCK_CLOSED),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Загрузить нового",
                callback_data="upload",
                icon_custom_emoji_id=ID.SEND,
            ),
            InlineKeyboardButton(
                text="Меню",
                callback_data="menu",
                icon_custom_emoji_id=ID.DOWN,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bot_actions_menu(record: BotRecord, *, is_running: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_running:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Перезапустить",
                    callback_data=f"act:restart:{record.id}",
                    icon_custom_emoji_id=ID.LOADING,
                ),
                InlineKeyboardButton(
                    text="Остановить",
                    callback_data=f"act:stop:{record.id}",
                    icon_custom_emoji_id=ID.CROSS,
                ),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Запустить",
                    callback_data=f"act:start:{record.id}",
                    icon_custom_emoji_id=ID.CHECK,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Логи",
                callback_data=f"act:logs:{record.id}",
                icon_custom_emoji_id=ID.DOWN,
            ),
            InlineKeyboardButton(
                text="Переименовать",
                callback_data=f"act:rename:{record.id}",
                icon_custom_emoji_id=ID.PENCIL,
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Заменить код",
                callback_data=f"act:replace:{record.id}",
                icon_custom_emoji_id=ID.CODE,
            ),
            InlineKeyboardButton(
                text="Удалить",
                callback_data=f"act:delete:{record.id}",
                icon_custom_emoji_id=ID.TRASH,
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="К списку",
                callback_data="bots",
                icon_custom_emoji_id=ID.DOWN,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"act:delete_confirm:{bot_id}",
                    icon_custom_emoji_id=ID.TRASH,
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"bot:{bot_id}",
                    icon_custom_emoji_id=ID.DOWN,
                ),
            ]
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="menu",
                    icon_custom_emoji_id=ID.DOWN,
                )
            ]
        ]
    )


def status_lines(sub: Subscription | None, bots: list[BotRecord]) -> str:
    from bothost import emoji as e

    lines: list[str] = []
    if sub and sub.is_active():
        lines.append(
            f"{e.CALENDAR} Подписка активна до "
            f"<b>{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>"
        )
        lines.append(f"{e.TAG} Лимит ботов: <b>{sub.bot_quota}</b>")
        lines.append(f"{e.COIN} Всего оплачено: {sub.total_paid_stars}")
    else:
        lines.append(f"{e.CALENDAR} Подписка не активна. Нажми /buy.")
    if bots:
        lines.append("")
        lines.append(f"{e.BOT} Боты ({len(bots)}):")
        status_emoji = {
            "running": e.CHECK,
            "stopped": e.LOCK_CLOSED,
            "crashed": e.CROSS,
            "expired": e.CLOCK,
        }
        for r in bots:
            marker = status_emoji.get(r.status, e.LOCK_CLOSED)
            lines.append(f"  {marker} {r.name} — {r.status}")
    else:
        lines.append("")
        lines.append(f"{e.PAPERCLIP} Загрузите .py или .zip — кнопка «Загрузить бота».")
    return "\n".join(lines)
