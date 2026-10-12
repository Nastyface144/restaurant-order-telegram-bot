"""Рабочий чат персонала: кнопки на карточках заказов."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

import config
from database import orders as orders_db
from database.models import OrderStatus
from keyboards import staff as kb
from keyboards.callbacks import StaffCb
from orders import workflow
from orders.statuses import REJECTABLE_STATUSES

router = Router(name="staff")


def _is_staff_chat(callback: CallbackQuery) -> bool:
    return bool(config.STAFF_CHAT_ID) and callback.message is not None \
        and callback.message.chat.id == config.STAFF_CHAT_ID


router.callback_query.filter(_is_staff_chat)


@router.callback_query(StaffCb.filter(F.a == "go"))
async def on_advance(callback: CallbackQuery, callback_data: StaffCb, bot: Bot) -> None:
    try:
        target = OrderStatus(callback_data.v)
    except ValueError:
        await callback.answer("Неизвестный статус", show_alert=True)
        return
    result = await workflow.advance(bot, callback_data.order, target, callback.from_user.full_name)
    await callback.answer(result.message, show_alert=not result.ok)


@router.callback_query(StaffCb.filter(F.a == "rej"))
async def on_reject_menu(callback: CallbackQuery, callback_data: StaffCb) -> None:
    order = await orders_db.get_order(callback_data.order)
    if order is None or order.status not in REJECTABLE_STATUSES:
        await callback.answer("Этот заказ уже нельзя отклонить", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=kb.reject_reasons(order))
    await callback.answer("Выберите причину")


@router.callback_query(StaffCb.filter(F.a == "back"))
async def on_reject_back(callback: CallbackQuery, callback_data: StaffCb) -> None:
    order = await orders_db.get_order(callback_data.order)
    if order is not None:
        await callback.message.edit_reply_markup(reply_markup=kb.order_actions(order))
    await callback.answer()


@router.callback_query(StaffCb.filter(F.a == "rr"))
async def on_reject(callback: CallbackQuery, callback_data: StaffCb, bot: Bot) -> None:
    index = int(callback_data.v) if callback_data.v.isdigit() else -1
    if not 0 <= index < len(config.REJECT_REASONS):
        await callback.answer("Неизвестная причина", show_alert=True)
        return
    result = await workflow.reject(bot, callback_data.order, config.REJECT_REASONS[index], callback.from_user.full_name)
    await callback.answer(result.message, show_alert=not result.ok)
