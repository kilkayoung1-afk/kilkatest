"""Inline keyboards used across the parent bot.

All button icons are set via `icon_custom_emoji_id` (Bot API 9.4+) — Premium
users see animated custom emoji, non-premium users see the button text without
an icon. Buttons therefore should NOT carry plain Unicode emojis in their
`text` field; the icon is the icon_custom_emoji_id, the text is plain text.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bothost.db import BotRecord, Subscription
from bothost.emoji import ID
from bothost.plans import Plan


def main_menu(*, has_active_sub: bool, bot_count: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_active_sub:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Загрузить бота",
                    callback_data="upload",
                    icon_custom_emoji_id=ID.SEND,
                ),
                InlineKeyboardButton(
                    text="Мои боты",
                    callback_data="bots",
                    icon_custom_emoji_id=ID.BOT,
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Подписка",
                    callback_data="status",
                    icon_custom_emoji_id=ID.STATS,
                ),
                InlineKeyboardButton(
                    text="Продлить",
                    callback_data="buy",
                    icon_custom_emoji_id=ID.CALENDAR,
                ),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Купить подписку",
                    callback_data="buy",
                    icon_custom_emoji_id=ID.COIN,
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Статус",
                    callback_data="status",
                    icon_custom_emoji_id=ID.STATS,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Помощь",
                callback_data="help",
                icon_custom_emoji_id=ID.INFO,
            ),
            InlineKeyboardButton(
                text="Политика",
                callback_data="terms",
                icon_custom_emoji_id=ID.LOCK_CLOSED,
            ),
        ]
    )
    if bot_count == 0 and has_active_sub:
        # subtle hint for the very first upload
        pass
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
