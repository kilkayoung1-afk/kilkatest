"""Хелперы для построения inline / reply клавиатур с premium emoji.

aiogram 3.x использует pydantic v2 с ``extra="allow"`` для типов API, поэтому
поле ``icon_custom_emoji_id`` (которое пока не описано в Bot API типах
aiogram, но передаётся в JSON) можно указывать напрямую как kwarg.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from aiogram.types import (
    KeyboardButton as TgKeyboardButton,
)

from telegram_bot_constructor.db.models import Keyboard, KeyboardButton
from telegram_bot_constructor.emoji import PremiumEmoji


def _emoji_id(icon: PremiumEmoji | str | None) -> str | None:
    if icon is None:
        return None
    if isinstance(icon, PremiumEmoji):
        return icon.emoji_id
    return str(icon)


def inline_button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    icon: PremiumEmoji | str | None = None,
) -> InlineKeyboardButton:
    kwargs: dict[str, object] = {"text": text}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    icon_id = _emoji_id(icon)
    if icon_id is not None:
        kwargs["icon_custom_emoji_id"] = icon_id
    return InlineKeyboardButton(**kwargs)  # type: ignore[arg-type]


def inline_kb(rows: Sequence[Sequence[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def reply_button(
    text: str,
    *,
    icon: PremiumEmoji | str | None = None,
) -> TgKeyboardButton:
    kwargs: dict[str, object] = {"text": text}
    icon_id = _emoji_id(icon)
    if icon_id is not None:
        kwargs["icon_custom_emoji_id"] = icon_id
    return TgKeyboardButton(**kwargs)  # type: ignore[arg-type]


def reply_kb(
    rows: Sequence[Sequence[TgKeyboardButton]],
    *,
    resize: bool = True,
    one_time: bool = False,
) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[list(r) for r in rows],
        resize_keyboard=resize,
        one_time_keyboard=one_time,
    )


# ---------- Сборка клавиатур из моделей БД ---------------------------------


def _group_buttons(buttons: list[KeyboardButton]) -> list[list[KeyboardButton]]:
    rows: dict[int, list[KeyboardButton]] = defaultdict(list)
    for b in buttons:
        rows[b.row].append(b)
    out: list[list[KeyboardButton]] = []
    for row_idx in sorted(rows):
        row = sorted(rows[row_idx], key=lambda b: b.col)
        out.append(row)
    return out


def build_inline_from_db(kb: Keyboard) -> InlineKeyboardMarkup | None:
    if kb.kind != "inline" or not kb.buttons:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for row in _group_buttons(list(kb.buttons)):
        out_row: list[InlineKeyboardButton] = []
        for b in row:
            if b.action == "url" and b.payload:
                out_row.append(
                    inline_button(b.text, url=b.payload, icon=b.icon_custom_emoji_id)
                )
            else:
                cb = b.payload or f"btn:{b.id}"
                out_row.append(
                    inline_button(b.text, callback_data=cb, icon=b.icon_custom_emoji_id)
                )
        rows.append(out_row)
    return inline_kb(rows)


def build_reply_from_db(kb: Keyboard) -> ReplyKeyboardMarkup | None:
    if kb.kind != "reply" or not kb.buttons:
        return None
    rows: list[list[TgKeyboardButton]] = []
    for row in _group_buttons(list(kb.buttons)):
        out_row: list[TgKeyboardButton] = []
        for b in row:
            out_row.append(reply_button(b.text, icon=b.icon_custom_emoji_id))
        rows.append(out_row)
    return reply_kb(rows, resize=kb.resize, one_time=kb.one_time)
