"""Subscription invoices via Telegram Stars."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from bothost import emoji as e
from bothost.config import Config
from bothost.db import Database
from bothost.keyboards import plans_menu, reply_keyboard
from bothost.plans import find_plan

logger = logging.getLogger(__name__)
router = Router(name="payment")


PLANS_HEADER = f"{e.COIN} <b>Тарифы</b> — выбери план:"


async def _show_plans(message: Message, cfg: Config) -> None:
    await message.answer(PLANS_HEADER, reply_markup=plans_menu(cfg.plans))


@router.callback_query(F.data == "buy")
async def cb_buy(call: CallbackQuery, cfg: Config) -> None:
    if isinstance(call.message, Message):
        await _show_plans(call.message, cfg)
    await call.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy_plan(call: CallbackQuery, cfg: Config) -> None:
    if call.data is None or not isinstance(call.message, Message):
        await call.answer()
        return
    plan_id = call.data.split(":", 1)[1]
    plan = find_plan(cfg.plans, plan_id)
    if plan is None:
        await call.answer("Тариф не найден", show_alert=True)
        return
    await call.message.answer_invoice(
        title=f"bothost · {plan.name}",
        description=(
            f"{plan.bots} {'бот' if plan.bots == 1 else 'ботов'} на {plan.days} дней. "
            "Покупки складываются: квота берётся максимальной, дни прибавляются."
        ),
        payload=f"plan:{plan.id}",
        currency="XTR",
        prices=[LabeledPrice(label=plan.name, amount=plan.stars)],
        provider_token="",
    )
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
    plan_id = payment.invoice_payload.removeprefix("plan:")
    plan = find_plan(cfg.plans, plan_id)
    if plan is None:
        logger.error("payment for unknown plan_id=%s", plan_id)
        await message.answer(
            f"{e.CROSS} Оплата получена, но тариф не найден в конфиге. Свяжитесь с администратором."
        )
        return
    sub = await db.apply_payment(
        tg_id=user.id,
        plan_id=plan.id,
        paid_stars=payment.total_amount,
        days=plan.days,
        bots=plan.bots,
        payment_charge_id=payment.telegram_payment_charge_id,
    )
    logger.info(
        "user %s paid %s⭐ on plan=%s, sub now: quota=%s expires=%s",
        user.id,
        payment.total_amount,
        plan.id,
        sub.bot_quota,
        sub.expires_at.isoformat(),
    )
    await message.answer(
        f"{e.CHECK} Оплата получена!\n"
        f"{e.CALENDAR} Подписка активна до "
        f"<b>{sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>\n"
        f"{e.TAG} Лимит ботов: <b>{sub.bot_quota}</b>\n\n"
        f"{e.PAPERCLIP} Можешь загружать <code>.py</code> или <code>.zip</code> файлы — "
        f"кнопка «Загрузить» снизу.",
        reply_markup=reply_keyboard(),
    )
