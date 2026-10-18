"""Кнопки карточки заказа в рабочем чате персонала."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

import config
from database.models import Order
from orders.statuses import REJECTABLE_STATUSES, next_transition

from .callbacks import StaffCb
from .common import DANGER, SUCCESS, button


def order_actions(order: Order) -> InlineKeyboardMarkup | None:
    row = []
    transition = next_transition(order.status, order.method)
    if transition:
        row.append(button(transition.button, StaffCb(a="go", order=order.id, v=transition.to).pack(), style=SUCCESS))
    if order.status in REJECTABLE_STATUSES:
        row.append(button("❌ Отклонить", StaffCb(a="rej", order=order.id).pack(), style=DANGER))
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def reject_reasons(order: Order) -> InlineKeyboardMarkup:
    rows = [
        [button(reason, StaffCb(a="rr", order=order.id, v=str(i)).pack(), style=DANGER)]
        for i, reason in enumerate(config.REJECT_REASONS)
    ]
    rows.append([button("← Назад", StaffCb(a="back", order=order.id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)
