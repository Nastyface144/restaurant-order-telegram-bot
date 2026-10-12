"""Клавиатура корзины."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import CartLine
from utils.format import money, truncate

from .callbacks import CartCb
from .common import home_button, nav_button


def cart(lines: list[CartLine], total: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n, line in enumerate(lines, 1):
        if line.item.is_available:
            kb.row(
                InlineKeyboardButton(text="➖", callback_data=CartCb(a="dec", line=line.id).pack()),
                InlineKeyboardButton(text=f"{n}. {truncate(line.item.title, 14)} · {line.qty}", callback_data="noop"),
                InlineKeyboardButton(text="➕", callback_data=CartCb(a="inc", line=line.id).pack()),
                InlineKeyboardButton(text="🗑", callback_data=CartCb(a="del", line=line.id).pack()),
            )
        else:
            kb.row(InlineKeyboardButton(
                text=f"🗑 Убрать «{truncate(line.item.title, 20)}»",
                callback_data=CartCb(a="del", line=line.id).pack(),
            ))
    if total > 0:
        kb.row(InlineKeyboardButton(text=f"✅ Оформить заказ · {money(total)}", callback_data=CartCb(a="checkout").pack()))
    kb.row(InlineKeyboardButton(text="🧹 Очистить корзину", callback_data=CartCb(a="clear").pack()))
    kb.row(nav_button("📖 Меню", "menu"), home_button())
    return kb.as_markup()


def empty_cart() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[nav_button("📖 Открыть меню", "menu")], [home_button()]])


def confirm_clear() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Да, очистить", callback_data=CartCb(a="clear_yes").pack())],
        [nav_button("⬅️ Нет, назад", "cart")],
    ])
