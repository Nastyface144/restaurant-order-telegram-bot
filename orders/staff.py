"""Отправка заказов в рабочий чат персонала."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import config
from database import orders as orders_db
from database import users
from database.models import Order, OrderStatus, PaymentMethod
from keyboards.staff import order_actions

from .formatting import staff_card

logger = logging.getLogger(__name__)


async def render_card(order: Order) -> str:
    user = await users.get_user(order.user_id)
    text = staff_card(order, user.username if user else None)
    if order.status == OrderStatus.REJECTED and order.payment_method == PaymentMethod.ONLINE and order.is_paid:
        text += "\n\n⚠️ <b>Заказ оплачен онлайн — оформите возврат в личном кабинете ЮKassa.</b>"
    return text


async def refresh_card(bot: Bot, order: Order) -> None:
    """Обновить карточку заказа в рабочем чате (текст и кнопки)."""
    if not config.STAFF_CHAT_ID or not order.staff_message_id:
        return
    try:
        await bot.edit_message_text(
            chat_id=config.STAFF_CHAT_ID,
            message_id=order.staff_message_id,
            text=await render_card(order),
            reply_markup=order_actions(order),
        )
    except TelegramAPIError as exc:
        if "message is not modified" not in str(exc):
            logger.warning("Не удалось обновить карточку заказа №%s: %s", order.id, exc)


async def send_new_order(bot: Bot, order: Order) -> None:
    """Новый заказ → карточка в рабочий чат. Сбой отправки не ломает оформление у клиента."""
    if not config.STAFF_CHAT_ID:
        logger.warning("STAFF_CHAT_ID не задан — заказ №%s никуда не отправлен", order.id)
        return
    try:
        message = await bot.send_message(
            config.STAFF_CHAT_ID, await render_card(order), reply_markup=order_actions(order)
        )
    except TelegramAPIError:
        logger.exception("Не удалось отправить заказ №%s в рабочий чат", order.id)
        await _alert_admins(bot, f"⚠️ Заказ №{order.id} не удалось отправить в рабочий чат. "
                                 f"Проверьте, что бот добавлен в группу и STAFF_CHAT_ID верный.")
        return
    await orders_db.set_staff_message(order.id, message.message_id)


async def _alert_admins(bot: Bot, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            logger.warning("Не удалось уведомить администратора %s", admin_id)
