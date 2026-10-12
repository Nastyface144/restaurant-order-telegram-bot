"""Кнопки, которые повторяются на многих экранах."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton

from .callbacks import Nav

BACK = "⬅️ Назад"
HOME = "🏠 Главное меню"


def nav_button(text: str, to: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=Nav(to=to).pack())


def home_button() -> InlineKeyboardButton:
    return nav_button(HOME, "main")


def cart_button(count: int) -> InlineKeyboardButton:
    text = f"🛒 Корзина · {count}" if count else "🛒 Корзина"
    return nav_button(text, "cart")
