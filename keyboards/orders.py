"""Клавиатуры раздела «Мои заказы»."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from database.models import Order
from orders.statuses import ACTIVE_STATUSES, status_label
from utils.format import money

from .callbacks import OrdersCb
from .common import BACK, PRIMARY, SUCCESS, button, home_button, nav_button


def orders_list(orders: list[Order]) -> InlineKeyboardMarkup:
    rows = [
        [button(
            f"№{o.id} · {o.created_at:%d.%m} · {money(o.total)} · {status_label(o.status, o.method)}",
            OrdersCb(a="view", id=o.id).pack(),
            style=PRIMARY if o.status in ACTIVE_STATUSES else None,  # активные заказы выделены
        )]
        for o in orders
    ]
    if not orders:
        rows.append([nav_button("🍕 Открыть меню", "menu", style=PRIMARY)])
    rows.append([home_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_details(order: Order) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("🔁 Повторить заказ", OrdersCb(a="repeat", id=order.id).pack(), style=SUCCESS)],
        [nav_button(BACK, "orders"), home_button()],
    ])


def open_order(order_id: int) -> InlineKeyboardMarkup:
    """Кнопка под уведомлением о статусе."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        button("🧾 Открыть заказ", OrdersCb(a="view", id=order_id).pack()),
    ]])
