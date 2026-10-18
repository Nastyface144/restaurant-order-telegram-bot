"""Общие элементы интерфейса: кнопки со стилем, навигация, корзина, прогресс-бар.

Цвет кнопок (Bot API 9+): PRIMARY — синяя «главное действие на экране»,
SUCCESS — зелёная «оформить / подтвердить / в корзину», DANGER — красная.
Старые клиенты Telegram просто показывают обычные кнопки.
"""

from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton

from utils.format import money

from .callbacks import Nav

PRIMARY = ButtonStyle.PRIMARY
SUCCESS = ButtonStyle.SUCCESS
DANGER = ButtonStyle.DANGER

BACK = "← Назад"
HOME = "🏠 На главную"


def button(text: str, callback_data: str | None = None, *, style: ButtonStyle | None = None,
           url: str | None = None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text=text, url=url, style=style)
    return InlineKeyboardButton(text=text, callback_data=callback_data or "noop", style=style)


def nav_button(text: str, to: str, *, style: ButtonStyle | None = None) -> InlineKeyboardButton:
    return button(text, Nav(to=to).pack(), style=style)


def home_button() -> InlineKeyboardButton:
    return nav_button(HOME, "main")


def cart_button(count: int, total: int, *, wide: bool = False) -> InlineKeyboardButton:
    """Корзина всегда под рукой и сразу с суммой: «🛒 2 · 1 280 ₽»."""
    if not count:
        return nav_button("🛒 Корзина" if wide else "🛒", "cart")
    text = f"🛒 Корзина · {count} шт · {money(total)}" if wide else f"🛒 {money(total)}"
    return nav_button(text, "cart", style=SUCCESS)


def progress_bar(step: int, total: int) -> str:
    """«▰▰▰▱▱» — сколько шагов пройдено."""
    step = max(0, min(step, total))
    return "▰" * step + "▱" * (total - step)
