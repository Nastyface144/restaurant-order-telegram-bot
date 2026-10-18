"""Клавиатура корзины."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import CartLine
from utils.format import money, truncate

from .callbacks import CartCb
from .common import DANGER, PRIMARY, SUCCESS, button, home_button, nav_button


def cart(lines: list[CartLine], total: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for line in lines:
        if line.item.is_available:
            # при одной штуке «минус» превращается в корзину для мусора — так понятнее, что позиция уйдёт
            minus = button("🗑", CartCb(a="del", line=line.id).pack()) if line.qty == 1 \
                else button("−", CartCb(a="dec", line=line.id).pack())
            kb.row(
                minus,
                button(f"{truncate(line.item.title, 16)} · {line.qty}", "noop"),
                button("+", CartCb(a="inc", line=line.id).pack()),
            )
        else:
            kb.row(button(f"🗑 Убрать «{truncate(line.item.title, 20)}»", CartCb(a="del", line=line.id).pack()))
    if total > 0:
        kb.row(button(f"✅ Оформить заказ · {money(total)}", CartCb(a="checkout").pack(), style=SUCCESS))
    kb.row(nav_button("+ Добавить ещё", "menu"), button("🧹 Очистить", CartCb(a="clear").pack()))
    kb.row(home_button())
    return kb.as_markup()


def empty_cart() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[nav_button("🍕 Открыть меню", "menu", style=PRIMARY)],
                                                 [home_button()]])


def confirm_clear() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("🧹 Да, очистить", CartCb(a="clear_yes").pack(), style=DANGER)],
        [nav_button("Нет, оставить", "cart")],
    ])
