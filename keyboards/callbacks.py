"""Callback data всех кнопок. Префиксы короткие: лимит Telegram — 64 байта."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class Nav(CallbackData, prefix="nav"):
    """Переход между разделами клиента."""

    to: str  # main | menu | cart | orders | booking | contacts | leave_table


class CategoryCb(CallbackData, prefix="cat"):
    id: int
    page: int = 0


class ItemCb(CallbackData, prefix="it"):
    """Карточка блюда. Выбор (размер, добавки, количество) хранится прямо в кнопке,
    поэтому карточка работает даже после перезапуска бота."""

    id: int
    s: str = ""     # код размера
    m: int = 0      # битовая маска выбранных добавок (по их порядку в меню)
    q: int = 1      # количество
    p: int = 0      # страница категории — чтобы «Назад» вернул туда же
    a: str = "v"    # v — показать, add — добавить в корзину, n — ничего (информационная кнопка)


class CartCb(CallbackData, prefix="cart"):
    a: str        # inc | dec | del | clear | clear_yes | checkout
    line: int = 0


class CheckoutCb(CallbackData, prefix="co"):
    a: str        # back | method | zone | addr | time | slots | phone | nocomment | pay | confirm
    v: str = ""


class PayCb(CallbackData, prefix="pay"):
    a: str  # cancel
    order: int
