"""Inline keyboards used across the parent bot.

All buttons attach two presentation hints:
- `icon_custom_emoji_id` — Premium custom-emoji icon shown before the label
  (Bot API 9.4+; falls back to plain text on non-Premium clients).
- `style` — accent color: "primary" (blue), "success" (green), "danger" (red);
  omitted = neutral grey. Clients that don't support `style` ignore it.

Buttons therefore should NOT carry plain Unicode emoji in their `text` field.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bothost.db import BotRecord, Subscription
from bothost.emoji import ID
from bothost.plans import Plan


def _btn(
    text: str,
    callback_data: str,
    *,
    style: str | None = None,
    icon: str | None = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        style=style,
        icon_custom_emoji_id=icon,
    )


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("Загрузить", "upload", style="primary", icon=ID.SEND),
                _btn("Мои боты", "bots", style="primary", icon=ID.BOT),
            ],
            [
                _btn("Купить", "buy", style="success", icon=ID.COIN),
                _btn("Подписка", "status", icon=ID.STATS),
            ],
            [
                _btn("Помощь", "help", icon=ID.INFO),
                _btn("Политика", "terms", icon=ID.LOCK_CLOSED),
            ],
        ]
    )


def plans_menu(plans: list[Plan]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plan in plans:
        rows.append(
            [
                _btn(
                    plan.label(),
                    f"buy:{plan.id}",
                    style="success",
                    icon=ID.COIN_SEND,
                )
            ]
        )
    rows.append([_btn("Назад", "menu", icon=ID.DOWN)])
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
                _btn(
                    r.name,
                    f"bot:{r.id}",
                    icon=icon_by_status.get(r.status, ID.LOCK_CLOSED),
                )
            ]
        )
    rows.append(
        [
            _btn("Загрузить нового", "upload", style="primary", icon=ID.SEND),
            _btn("Меню", "menu", icon=ID.DOWN),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bot_actions_menu(record: BotRecord, *, is_running: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_running:
        rows.append(
            [
                _btn(
                    "Перезапустить",
                    f"act:restart:{record.id}",
                    style="primary",
                    icon=ID.LOADING,
                ),
                _btn(
                    "Остановить",
                    f"act:stop:{record.id}",
                    style="danger",
                    icon=ID.CROSS,
                ),
            ]
        )
    else:
        rows.append(
            [
                _btn(
                    "Запустить",
                    f"act:start:{record.id}",
                    style="success",
                    icon=ID.CHECK,
                )
            ]
        )
    rows.append(
        [
            _btn("Логи", f"act:logs:{record.id}", icon=ID.DOWN),
            _btn("Переименовать", f"act:rename:{record.id}", icon=ID.PENCIL),
        ]
    )
    rows.append(
        [
            _btn(
                "Заменить код",
                f"act:replace:{record.id}",
                style="primary",
                icon=ID.CODE,
            ),
            _btn(
                "Удалить",
                f"act:delete:{record.id}",
                style="danger",
                icon=ID.TRASH,
            ),
        ]
    )
    rows.append([_btn("К списку", "bots", icon=ID.DOWN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "Да, удалить",
                    f"act:delete_confirm:{bot_id}",
                    style="danger",
                    icon=ID.TRASH,
                ),
                _btn("Отмена", f"bot:{bot_id}", icon=ID.DOWN),
            ]
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Отмена", "menu", icon=ID.DOWN)]])


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Меню", "menu", icon=ID.DOWN)]])


def status_lines(sub: Subscription | None, bots: list[BotRecord]) -> str:
    from bothost import emoji as e

    lines: list[str] = []
    if sub and sub.is_active():
        lines.append(
            f"{e.CALENDAR} Подписка активна до "
            f"<b>{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>"
        )
        mem_text = (
            f"{sub.mem_mb // 1024} ГБ"
            if sub.mem_mb >= 1024 and sub.mem_mb % 1024 == 0
            else f"{sub.mem_mb} МБ"
        )
        disk_text = (
            f"{sub.disk_mb // 1024} ГБ"
            if sub.disk_mb >= 1024 and sub.disk_mb % 1024 == 0
            else f"{sub.disk_mb} МБ"
        )
        lines.append(
            f"{e.TAG} Лимиты бота: <b>{mem_text} RAM · {sub.cpu_quota:g} CPU · {disk_text} диск</b>"
        )
        lines.append(f"{e.COIN} Всего оплачено: {sub.total_paid_stars}")
    else:
        lines.append(f"{e.CALENDAR} Подписка не активна. Нажми «Купить».")
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
        lines.append(f"{e.PAPERCLIP} Загрузите .py или .zip — кнопка «Загрузить».")
    return "\n".join(lines)
