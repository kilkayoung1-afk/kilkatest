"""Telegram Stars invoice + payment confirmation."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from bothost.config import Config
from bothost.db import Database

logger = logging.getLogger(__name__)
router = Router(name="payment")


async def _send_invoice(message: Message, cfg: Config) -> None:
    await message.answer_invoice(
        title=f"Подписка bothost — {cfg.subscription_days} дней",
        description=(
            f"Запуск твоего Python-бота на {cfg.subscription_days} дней. "
            "Можно продлевать сколько угодно — время добавляется поверх текущего."
        ),
        payload=f"bothost-sub-{cfg.subscription_days}d",
        currency="XTR",
        prices=[LabeledPrice(label=f"{cfg.subscription_days} дней", amount=cfg.subscription_stars)],
        provider_token="",
    )


@router.message(Command("buy"))
async def handle_buy(message: Message, cfg: Config) -> None:
    await _send_invoice(message, cfg)


@router.callback_query(F.data == "buy")
async def cb_buy(call: CallbackQuery, cfg: Config) -> None:
    if isinstance(call.message, Message):
        await _send_invoice(call.message, cfg)
    await call.answer()


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, cfg: Config, db: Database) -> None:
    payment = message.successful_payment
    user = message.from_user
    if payment is None or user is None:
        return
    await db.upsert_user(user.id, user.username)
    sub = await db.add_subscription(
        tg_id=user.id,
        days=cfg.subscription_days,
        paid_stars=payment.total_amount,
        payment_charge_id=payment.telegram_payment_charge_id,
    )
    logger.info(
        "user %s paid %s stars, subscription valid until %s",
        user.id,
        payment.total_amount,
        sub.expires_at.isoformat(),
    )
    await message.answer(
        "✅ Оплата получена!\n"
        f"Подписка активна до <b>{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>.\n\n"
        "Теперь пришли мне <b>.py файл</b> со своим ботом — я его запущу."
    )
