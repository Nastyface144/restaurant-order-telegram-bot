"""Смена статуса заказа персоналом: запись в БД, уведомление клиента, обновление карточки."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from database import orders as orders_db
from database import users
from database.models import Order, OrderStatus, PaymentMethod
from keyboards.orders import open_order

from . import staff
from .statuses import REJECTABLE_STATUSES, client_notification, previous_statuses

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeResult:
    ok: bool
    order: Order | None
    message: str  # короткий ответ сотруднику (всплывающее уведомление)


async def notify_client(bot: Bot, order: Order) -> bool:
    text = client_notification(order.id, order.status, order.method, order.reject_reason)
    if not text:
        return False
    if order.status == OrderStatus.REJECTED and order.payment_method == PaymentMethod.ONLINE and order.is_paid:
        text += "\n💳 Деньги вернём на карту — возврат обычно занимает до 3 рабочих дней."
    try:
        await bot.send_message(order.user_id, text, reply_markup=open_order(order.id))
        return True
    except TelegramForbiddenError:
        await users.mark_blocked(order.user_id)
        logger.info("Клиент %s заблокировал бота — уведомление о заказе №%s не доставлено", order.user_id, order.id)
    except TelegramAPIError:
        logger.exception("Не удалось уведомить клиента о заказе №%s", order.id)
    return False


async def _after_change(bot: Bot, order_id: int) -> tuple[Order, bool]:
    order = await orders_db.get_order(order_id)
    notified = await notify_client(bot, order)
    await staff.refresh_card(bot, order)
    return order, notified


async def advance(bot: Bot, order_id: int, target: OrderStatus, staff_name: str) -> ChangeResult:
    order = await orders_db.get_order(order_id)
    if order is None:
        return ChangeResult(False, None, "Заказ не найден")
    expected = previous_statuses(target, order.method)
    if not await orders_db.update_status(order_id, target, expected=expected, changed_by=staff_name):
        # Кто-то уже нажал кнопку — просто показываем актуальное состояние
        await staff.refresh_card(bot, order)
        return ChangeResult(False, order, "Статус уже изменён")

    if target == OrderStatus.COMPLETED and order.payment_method != PaymentMethod.ONLINE:
        await orders_db.mark_paid_on_receipt(order_id)
    order, notified = await _after_change(bot, order_id)
    logger.info("Заказ №%s → %s (%s)", order_id, target, staff_name)
    return ChangeResult(True, order, "Клиент уведомлён ✅" if notified else "Статус изменён")


async def reject(bot: Bot, order_id: int, reason: str, staff_name: str) -> ChangeResult:
    order = await orders_db.get_order(order_id)
    if order is None:
        return ChangeResult(False, None, "Заказ не найден")
    if not await orders_db.update_status(
        order_id, OrderStatus.REJECTED, expected=REJECTABLE_STATUSES, changed_by=staff_name, reject_reason=reason
    ):
        await staff.refresh_card(bot, order)
        return ChangeResult(False, order, "Заказ уже нельзя отклонить")
    order, notified = await _after_change(bot, order_id)
    logger.info("Заказ №%s отклонён (%s): %s", order_id, staff_name, reason)
    return ChangeResult(True, order, "Заказ отклонён, клиент уведомлён" if notified else "Заказ отклонён")
