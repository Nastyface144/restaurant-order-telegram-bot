"""Клавиатуры меню: категории, список блюд, карточка блюда."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database.cart import MAX_QTY
from database.models import Category, MenuItem
from utils.format import money

from .callbacks import CategoryCb, ItemCb
from .common import BACK, PRIMARY, SUCCESS, button, cart_button, nav_button

ITEMS_PER_PAGE = 8


def _bottom(back_data: str, cart_count: int, cart_total: int) -> list:
    row = [button(BACK, back_data)]
    if config.FEATURES.ordering:
        row.append(cart_button(cart_count, cart_total))
    return row


def categories(items: list[Category], cart_count: int, cart_total: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for category in items:
        kb.add(button(category.label, CategoryCb(id=category.id).pack()))
    kb.adjust(2)
    row = [nav_button(BACK, "main")]
    if config.FEATURES.ordering:
        row.append(cart_button(cart_count, cart_total))
    kb.row(*row)
    return kb.as_markup()


def price_from(item: MenuItem) -> str:
    return f"от {money(item.min_price)}" if len(item.sizes) > 1 else money(item.min_price)


def category_items(category: Category, items: list[MenuItem], page: int, cart_count: int,
                   cart_total: int) -> InlineKeyboardMarkup:
    pages = max(1, -(-len(items) // ITEMS_PER_PAGE))
    page = min(max(page, 0), pages - 1)
    chunk = items[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

    kb = InlineKeyboardBuilder()
    for item in chunk:
        kb.row(button(f"{item.title} · {price_from(item)}", ItemCb(id=item.id, p=page).pack()))
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(button("◀️", CategoryCb(id=category.id, page=page - 1).pack()))
        nav.append(button(f"{page + 1} / {pages}", "noop"))
        if page < pages - 1:
            nav.append(button("▶️", CategoryCb(id=category.id, page=page + 1).pack()))
        kb.row(*nav)
    row = [nav_button(BACK, "menu")]
    if config.FEATURES.ordering:
        row.append(cart_button(cart_count, cart_total))
    kb.row(*row)
    return kb.as_markup()


def item_card(item: MenuItem, size_code: str, mask: int, qty: int, page: int, cart_count: int,
              cart_total: int) -> InlineKeyboardMarkup:
    def state(**changes) -> str:
        values = {"id": item.id, "s": size_code, "m": mask, "q": qty, "p": page, "a": "v"}
        values.update(changes)
        return ItemCb(**values).pack()

    kb = InlineKeyboardBuilder()

    if len(item.sizes) > 1:
        kb.row(*[
            button(
                ("✓ " if size.code == size_code else "") + f"{size.title} · {money(size.price)}",
                state(s=size.code),
                style=PRIMARY if size.code == size_code else None,
            )
            for size in item.sizes
        ])

    if item.addons:
        buttons = []
        for i, addon in enumerate(item.addons):
            selected = bool(mask >> i & 1)
            buttons.append(button(
                f"{'✓' if selected else '+'} {addon.title} {money(addon.price)}",
                state(m=mask ^ (1 << i)),
                style=SUCCESS if selected else None,
            ))
        for start in range(0, len(buttons), 2):
            kb.row(*buttons[start:start + 2])

    if config.FEATURES.ordering:
        total = item.unit_price(size_code, item.addon_codes_from_mask(mask)) * qty
        kb.row(
            button("−", state(q=max(1, qty - 1))),
            button(f"{qty} шт", state(a="n")),
            button("+", state(q=min(MAX_QTY, qty + 1))),
        )
        kb.row(button(f"🛒 В корзину · {money(total)}", state(a="add"), style=SUCCESS))

    kb.row(*_bottom(CategoryCb(id=item.category_id, page=page).pack(), cart_count, cart_total))
    return kb.as_markup()
