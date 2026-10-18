"""Клавиатуры админ-панели."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Category, MenuItem
from utils.format import truncate

from .callbacks import AdminCb
from .common import DANGER, PRIMARY, SUCCESS, button


def _btn(text: str, a: str, v: int = 0, style=None) -> InlineKeyboardButton:
    return button(text, AdminCb(a=a, v=v).pack(), style=style)


def _back(to: str = "home", v: int = 0) -> list[InlineKeyboardButton]:
    return [_btn("← Назад", to, v)]


def dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🧾 Заказы сегодня", "orders", style=PRIMARY), _btn("📅 Брони сегодня", "bookings", style=PRIMARY)],
        [_btn("🚫 Стоп-лист", "stop"), _btn("📣 Рассылка", "bc")],
        [_btn("🔄 Обновить", "home")],
    ])


def back_to_dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[_back()])


def stop_categories(categories: list[Category], stopped: dict[int, int]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for category in categories:
        count = stopped.get(category.id, 0)
        suffix = f" · 🚫 {count}" if count else ""
        kb.add(_btn(f"{category.label}{suffix}", "stopcat", category.id))
    kb.adjust(2)
    kb.row(*_back())
    return kb.as_markup()


def stop_items(category: Category, items: list[MenuItem]) -> InlineKeyboardMarkup:
    """Одна кнопка — одно блюдо: нажатие скрывает его или возвращает в меню."""
    rows = [
        [_btn(f"{'✅' if item.is_available else '🚫'} {truncate(item.title, 30)}", "toggle", item.id,
              style=SUCCESS if item.is_available else DANGER)]
        for item in items
    ]
    rows.append(_back("stop"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_wait() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("✖️ Отмена", "bc_cancel")]])


def broadcast_confirm(recipients: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"📣 Отправить ({recipients})", "bc_send", style=SUCCESS)],
        [_btn("✏️ Другое сообщение", "bc"), _btn("✖️ Отмена", "bc_cancel")],
    ])
