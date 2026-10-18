"""Клавиатуры главного экрана и контактов."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database.models import Order
from orders.statuses import short_status

from .callbacks import OrdersCb
from .common import PRIMARY, button, cart_button, home_button, nav_button


def main_menu(cart_count: int, cart_total: int, *, table_no: int | None, accepting: bool,
              active_order: Order | None) -> InlineKeyboardMarkup:
    """Главный экран: одно главное действие крупно, остальное — второстепенно."""
    kb = InlineKeyboardBuilder()
    if not config.FEATURES.ordering:
        kb.row(nav_button("📖 Посмотреть меню", "menu", style=PRIMARY))
    elif table_no:
        kb.row(nav_button(f"🍕 Заказать к столу №{table_no}", "menu", style=PRIMARY))
    elif accepting:
        kb.row(nav_button("🍕 Открыть меню и заказать", "menu", style=PRIMARY))
    else:
        kb.row(nav_button("🍕 Заказать заранее", "menu", style=PRIMARY))

    if config.FEATURES.ordering and cart_count:
        kb.row(cart_button(cart_count, cart_total, wide=True))
    if active_order:
        kb.row(button(f"📦 Заказ №{active_order.id} · {short_status(active_order)}",
                      OrdersCb(a="view", id=active_order.id).pack()))

    second = []
    if config.FEATURES.ordering:
        second.append(nav_button("📦 Мои заказы", "orders"))
    if config.FEATURES.booking:
        second.append(nav_button("📅 Забронировать", "booking"))
    if second:
        kb.row(*second)
    kb.row(nav_button("📍 Контакты и часы работы", "contacts"))
    if table_no:
        kb.row(nav_button("🚪 Я уже ушёл из-за стола", "leave_table"))
    return kb.as_markup()


def contacts() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if config.VENUE_MAP_URL:
        kb.row(button("🗺 Открыть на карте", url=config.VENUE_MAP_URL, style=PRIMARY))
    kb.row(home_button())
    return kb.as_markup()
