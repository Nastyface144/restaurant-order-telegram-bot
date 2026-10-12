"""Клавиатуры клиентской части."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config

from .common import cart_button, home_button, nav_button


def main_menu(cart_count: int, at_table: bool) -> InlineKeyboardMarkup:
    """Главное меню: показываются только включённые разделы."""
    kb = InlineKeyboardBuilder()
    if config.FEATURES.ordering:
        kb.row(nav_button("📖 Меню", "menu"), cart_button(cart_count))
        kb.row(nav_button("📦 Мои заказы", "orders"))
    else:
        kb.row(nav_button("📖 Меню", "menu"))
    if config.FEATURES.booking:
        kb.row(nav_button("📅 Забронировать столик", "booking"))
    kb.row(nav_button("📍 Контакты", "contacts"))
    if at_table:
        kb.row(nav_button("🚪 Я уже не за столом", "leave_table"))
    return kb.as_markup()


def contacts() -> InlineKeyboardMarkup:
    rows = []
    if config.VENUE_MAP_URL:
        rows.append([InlineKeyboardButton(text="🗺 Открыть на карте", url=config.VENUE_MAP_URL)])
    rows.append([home_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)
