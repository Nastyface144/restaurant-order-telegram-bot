"""Отправка заказов в рабочий чат персонала."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import config
from database import orders as orders_db
from database import users
from database.models import Order

from .formatting import staff_card

logger = logging.getLogger(__name__)


async def render_card(order: Order) -> str:
    user = await users.get_user(order.user_id)
    return staff_card(order, user.username if user else None)


async def send_new_order(bot: Bot, order: Order) -> None:
    """Новый заказ → карточка в рабочий чат. Сбой отправки не ломает оформление у клиента."""
    if not config.STAFF_CHAT_ID:
        logger.warning("STAFF_CHAT_ID не задан — заказ №%s никуда не отправлен", order.id)
        return
    try:
        message = await bot.send_message(config.STAFF_CHAT_ID, await render_card(order))
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
