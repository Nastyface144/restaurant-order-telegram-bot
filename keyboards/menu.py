"""Клавиатуры меню: категории, список блюд, карточка блюда."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database.cart import MAX_QTY
from database.models import Category, MenuItem
from utils.format import money

from .callbacks import CategoryCb, ItemCb
from .common import BACK, cart_button, nav_button

ITEMS_PER_PAGE = 8


def categories(items: list[Category], cart_count: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for category in items:
        kb.button(text=category.label, callback_data=CategoryCb(id=category.id))
    kb.adjust(2)
    bottom = [nav_button(BACK, "main")]
    if config.FEATURES.ordering:
        bottom.append(cart_button(cart_count))
    kb.row(*bottom)
    return kb.as_markup()


def category_items(category: Category, items: list[MenuItem], page: int, cart_count: int) -> InlineKeyboardMarkup:
    pages = max(1, -(-len(items) // ITEMS_PER_PAGE))
    page = min(max(page, 0), pages - 1)
    chunk = items[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

    kb = InlineKeyboardBuilder()
    for item in chunk:
        price = f"от {money(item.min_price)}" if len(item.sizes) > 1 else money(item.min_price)
        kb.row(InlineKeyboardButton(
            text=f"{item.title} · {price}",
            callback_data=ItemCb(id=item.id, p=page).pack(),
        ))
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=CategoryCb(id=category.id, page=page - 1).pack()))
        nav.append(InlineKeyboardButton(text=f"{page + 1} / {pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=CategoryCb(id=category.id, page=page + 1).pack()))
        kb.row(*nav)
    bottom = [nav_button(BACK, "menu")]
    if config.FEATURES.ordering:
        bottom.append(cart_button(cart_count))
    kb.row(*bottom)
    return kb.as_markup()


def item_card(item: MenuItem, size_code: str, mask: int, qty: int, page: int, cart_count: int) -> InlineKeyboardMarkup:
    def state(**changes) -> str:
        values = {"id": item.id, "s": size_code, "m": mask, "q": qty, "p": page, "a": "v"}
        values.update(changes)
        return ItemCb(**values).pack()

    kb = InlineKeyboardBuilder()

    if len(item.sizes) > 1:
        kb.row(*[
            InlineKeyboardButton(
                text=f"{'✅ ' if size.code == size_code else ''}{size.title} · {money(size.price)}",
                callback_data=state(s=size.code),
            )
            for size in item.sizes
        ], width=3)

    if item.addons:
        buttons = []
        for i, addon in enumerate(item.addons):
            selected = bool(mask >> i & 1)
            buttons.append(InlineKeyboardButton(
                text=f"{'✅' if selected else '➕'} {addon.title} +{money(addon.price)}",
                callback_data=state(m=mask ^ (1 << i)),
            ))
        for start in range(0, len(buttons), 2):
            kb.row(*buttons[start:start + 2])

    if config.FEATURES.ordering:
        total = item.unit_price(size_code, item.addon_codes_from_mask(mask)) * qty
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=state(q=max(1, qty - 1))),
            InlineKeyboardButton(text=f"{qty} шт.", callback_data=state(a="n")),
            InlineKeyboardButton(text="➕", callback_data=state(q=min(MAX_QTY, qty + 1))),
        )
        kb.row(InlineKeyboardButton(text=f"🛒 Добавить · {money(total)}", callback_data=state(a="add")))

    bottom = [InlineKeyboardButton(text=BACK, callback_data=CategoryCb(id=item.category_id, page=page).pack())]
    if config.FEATURES.ordering:
        bottom.append(cart_button(cart_count))
    kb.row(*bottom)
    return kb.as_markup()
