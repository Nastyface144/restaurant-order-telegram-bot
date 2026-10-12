"""Кнопки карточки заказа в рабочем чате персонала."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from database.models import Order
from orders.statuses import REJECTABLE_STATUSES, next_transition

from .callbacks import StaffCb


def order_actions(order: Order) -> InlineKeyboardMarkup | None:
    row = []
    transition = next_transition(order.status, order.method)
    if transition:
        row.append(InlineKeyboardButton(
            text=transition.button,
            callback_data=StaffCb(a="go", order=order.id, v=transition.to).pack(),
        ))
    if order.status in REJECTABLE_STATUSES:
        row.append(InlineKeyboardButton(text="❌ Отклонить", callback_data=StaffCb(a="rej", order=order.id).pack()))
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def reject_reasons(order: Order) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=reason, callback_data=StaffCb(a="rr", order=order.id, v=str(i)).pack())]
        for i, reason in enumerate(config.REJECT_REASONS)
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=StaffCb(a="back", order=order.id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)
