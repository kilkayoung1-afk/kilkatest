"""Inline keyboards used across the parent bot."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bothost.db import BotRecord, Subscription
from bothost.plans import Plan


def main_menu(*, has_active_sub: bool, bot_count: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_active_sub:
        rows.append(
            [
                InlineKeyboardButton(text="📤 Загрузить бота", callback_data="upload"),
                InlineKeyboardButton(text="🤖 Мои боты", callback_data="bots"),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="📊 Подписка", callback_data="status"),
                InlineKeyboardButton(text="➕ Продлить", callback_data="buy"),
            ]
        )
    else:
        rows.append([InlineKeyboardButton(text="⭐ Купить подписку", callback_data="buy")])
        rows.append([InlineKeyboardButton(text="📊 Статус", callback_data="status")])
    rows.append([InlineKeyboardButton(text="❓ Помощь", callback_data="help")])
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
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bots_list_menu(records: list[BotRecord]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for r in records:
        marker = {"running": "🟢", "stopped": "⚪", "crashed": "🔴", "expired": "⏰"}.get(
            r.status, "⚪"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker} {r.name}",
                    callback_data=f"bot:{r.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="📤 Загрузить нового", callback_data="upload"),
            InlineKeyboardButton(text="« Меню", callback_data="menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bot_actions_menu(record: BotRecord, *, is_running: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_running:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Перезапустить", callback_data=f"act:restart:{record.id}"
                ),
                InlineKeyboardButton(text="⏹ Остановить", callback_data=f"act:stop:{record.id}"),
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="▶️ Запустить", callback_data=f"act:start:{record.id}")]
        )
    rows.append(
        [
            InlineKeyboardButton(text="📜 Логи", callback_data=f"act:logs:{record.id}"),
            InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"act:rename:{record.id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="🔁 Заменить код", callback_data=f"act:replace:{record.id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"act:delete:{record.id}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="« К списку", callback_data="bots")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Удалить", callback_data=f"act:delete_confirm:{bot_id}"
                ),
                InlineKeyboardButton(text="« Отмена", callback_data=f"bot:{bot_id}"),
            ]
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="menu")]]
    )


def status_lines(sub: Subscription | None, bots: list[BotRecord]) -> str:
    lines: list[str] = []
    if sub and sub.is_active():
        lines.append(
            f"📅 Подписка активна до <b>{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>"
        )
        lines.append(f"🎟 Лимит ботов: <b>{sub.bot_quota}</b>")
        lines.append(f"⭐ Всего оплачено: {sub.total_paid_stars}")
    else:
        lines.append("📅 Подписка не активна. Нажмите /buy.")
    if bots:
        lines.append("")
        lines.append(f"🤖 Боты ({len(bots)}):")
        for r in bots:
            marker = {"running": "🟢", "stopped": "⚪", "crashed": "🔴", "expired": "⏰"}.get(
                r.status, "⚪"
            )
            lines.append(f"  {marker} {r.name} — {r.status}")
    else:
        lines.append("")
        lines.append("🤖 У вас пока нет ботов.")
    return "\n".join(lines)
