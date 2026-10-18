"""Создание заказа из корзины."""

from __future__ import annotations

import logging

from aiogram import Bot

from database import orders as orders_db
from database import users
from database.models import CartLine, Order, OrderMethod, OrderStatus, PaymentMethod

from . import pricing, scheduler, staff
from .checkout import Draft, parse_time

logger = logging.getLogger(__name__)


async def place_order(bot: Bot, *, user_id: int, customer_name: str, draft: Draft, lines: list[CartLine]) -> Order:
    """Создаёт заказ. Онлайн-оплата: заказ ждёт оплаты, корзина сохраняется до её успеха.
    Иначе заказ сразу уходит персоналу, а корзина очищается."""
    method = OrderMethod(draft.method)
    items = pricing.to_order_items(lines)
    items_total = sum(i.total for i in items)
    delivery = method == OrderMethod.DELIVERY
    fee = pricing.delivery_fee(items_total) if delivery else 0
    online = draft.payment == PaymentMethod.ONLINE

    order_id = await orders_db.create_order(
        user_id=user_id,
        status=OrderStatus.PENDING_PAYMENT if online else OrderStatus.NEW,
        method=method,
        customer_name=customer_name,
        phone=draft.phone,
        payment_method=PaymentMethod(draft.payment),
        items=items,
        delivery_fee=fee,
        address=draft.address if delivery else None,
        table_no=draft.table_no if method == OrderMethod.TABLE else None,
        comment=draft.comment,
        scheduled_at=parse_time(draft.time) if method != OrderMethod.TABLE else None,
        clear_cart=not online,
    )
    await users.save_contact_details(user_id, phone=draft.phone, address=draft.address if delivery else None)
    order = await orders_db.get_order(order_id)
    logger.info("Заказ №%s создан: %s, %s, %s ₽", order.id, method, order.payment_method, order.total)
    if not online:
        await on_order_confirmed(bot, order)
    return order


async def on_order_confirmed(bot: Bot, order: Order) -> None:
    """Заказ подтверждён (оформлен или оплачен) — передаём персоналу."""
    await staff.send_new_order(bot, order)
    scheduler.schedule_order_reminder(order)
