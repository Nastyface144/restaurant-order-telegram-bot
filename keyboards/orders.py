"""Клавиатуры раздела «Мои заказы»."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Order
from orders.statuses import status_label
from utils.format import money

from .callbacks import OrdersCb
from .common import BACK, home_button, nav_button


def orders_list(orders: list[Order]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"№{o.id} · {o.created_at:%d.%m} · {money(o.total)} · {status_label(o.status, o.method)}",
            callback_data=OrdersCb(a="view", id=o.id).pack(),
        )]
        for o in orders
    ]
    if not orders:
        rows.append([nav_button("📖 Открыть меню", "menu")])
    rows.append([home_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_details(order: Order) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Повторить заказ", callback_data=OrdersCb(a="repeat", id=order.id).pack())],
        [nav_button(BACK, "orders"), home_button()],
    ])


def open_order(order_id: int) -> InlineKeyboardMarkup:
    """Кнопка под уведомлением о статусе."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🧾 Открыть заказ", callback_data=OrdersCb(a="view", id=order_id).pack()),
    ]])
