"""Telegram-обработчики оплаты: проверка перед списанием, успешный платёж, отмена счёта."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

import config
from database import cart
from database import orders as orders_db
from database.models import OrderStatus
from keyboards.callbacks import PayCb
from orders import service
from payments.invoice import parse_payload, to_minor

from .cart import show_cart
from .checkout import show_order_placed

logger = logging.getLogger(__name__)
router = Router(name="payment")


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    """Последняя проверка перед списанием денег. Ответить нужно в течение 10 секунд."""
    order_id = parse_payload(query.invoice_payload)
    order = await orders_db.get_order(order_id) if order_id else None

    error = None
    if order is None or order.user_id != query.from_user.id:
        error = "Заказ не найден. Оформите его, пожалуйста, заново."
    elif order.status != OrderStatus.PENDING_PAYMENT:
        error = "Этот заказ уже оплачен или отменён."
    elif query.currency != config.CURRENCY or query.total_amount != to_minor(order.total):
        error = "Сумма заказа изменилась. Оформите заказ заново."

    if error:
        logger.warning("Оплата заказа %s отклонена: %s", order_id, error)
        await query.answer(ok=False, error_message=error)
    else:
        await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, bot: Bot) -> None:
    payment = message.successful_payment
    order_id = parse_payload(payment.invoice_payload)
    if order_id is None:
        logger.error("Платёж с неизвестным payload: %s", payment.invoice_payload)
        return

    paid = await orders_db.mark_paid(order_id, payment.telegram_payment_charge_id, payment.provider_payment_charge_id)
    order = await orders_db.get_order(order_id)
    if not paid or order is None:
        # Повторное уведомление о том же платеже — ничего не делаем
        logger.warning("Повторное или неожиданное уведомление об оплате заказа %s", order_id)
        return

    logger.info("Заказ №%s оплачен онлайн (%s)", order_id, payment.provider_payment_charge_id)
    await cart.clear_cart(order.user_id)
    await service.on_order_confirmed(bot, order)
    await show_order_placed(bot, message.chat.id, order)


@router.callback_query(PayCb.filter(F.a == "cancel"))
async def on_cancel_invoice(callback: CallbackQuery, callback_data: PayCb, bot: Bot) -> None:
    order = await orders_db.get_order(callback_data.order)
    if order and order.user_id == callback.from_user.id:
        await orders_db.update_status(order.id, OrderStatus.CANCELLED, expected=[OrderStatus.PENDING_PAYMENT],
                                      changed_by="клиент")
    await show_cart(bot, callback, notice="Оплата отменена — корзина на месте 👌")
    await callback.answer()
