"""Клавиатуры оформления заказа."""

from __future__ import annotations

from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database.models import OrderMethod, PaymentMethod
from orders import pricing
from orders.checkout import METHOD_TITLES, PAYMENT_TITLES, TIME_ASAP, slot_value
from utils.format import format_phone, money, truncate
from utils.timeutil import human_date

from .callbacks import CheckoutCb
from .common import home_button, nav_button

BACK = "⬅️ Назад"


def _btn(text: str, a: str, v: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=CheckoutCb(a=a, v=v).pack())


def _back_row() -> list[InlineKeyboardButton]:
    return [_btn(BACK, "back")]


def methods(options: list[OrderMethod]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(METHOD_TITLES[m], "method", m) for m in options],
        _back_row(),
    ])


def zones(items_total: int) -> InlineKeyboardMarkup:
    rows = []
    for zone in config.DELIVERY_ZONES:
        if pricing.min_order_shortfall(zone, items_total):
            label = f"🔒 {zone.title} · от {money(zone.min_order)}"
        else:
            fee = pricing.delivery_fee(zone, items_total)
            label = f"{zone.title} · {'бесплатно' if fee == 0 else money(fee)}"
        rows.append([_btn(label, "zone", str(zone.id))])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def address(saved: str | None) -> InlineKeyboardMarkup:
    rows = []
    if saved:
        rows.append([_btn(f"📍 {truncate(saved, 40)}", "addr")])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_delivery(asap: bool) -> InlineKeyboardMarkup:
    rows = []
    if asap:
        rows.append([_btn("⚡ Как можно скорее", "time", TIME_ASAP)])
    rows.append([_btn("🕐 Ко времени", "slots")])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_pickup(quick: list[int]) -> InlineKeyboardMarkup:
    rows = []
    if quick:
        rows.append([_btn(f"Через {m} мин", "time", f"in_{m}") for m in quick])
    rows.append([_btn("🕐 К конкретному времени", "slots")])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slots(items: list[datetime], today: date, back_to_choice: bool) -> InlineKeyboardMarkup:
    """Слоты, сгруппированные по дням: заголовок дня и время по 4 в ряд."""
    kb = InlineKeyboardBuilder()
    current_day = None
    row: list[InlineKeyboardButton] = []
    for slot in items:
        if slot.date() != current_day:
            if row:
                kb.row(*row)
                row = []
            current_day = slot.date()
            kb.row(InlineKeyboardButton(text=f"📅 {human_date(current_day, today).capitalize()}", callback_data="noop"))
        row.append(_btn(f"{slot:%H:%M}", "time", slot_value(slot)))
        if len(row) == 4:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    # «Назад» со списка слотов ведёт к выбору «скорее / ко времени», если он был
    kb.row(_btn(BACK, "time_menu" if back_to_choice else "back"))
    return kb.as_markup()


def phone(saved: str | None) -> InlineKeyboardMarkup:
    rows = []
    if saved:
        rows.append([_btn(f"📞 {format_phone(saved)}", "phone")])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def comment() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("➡️ Без комментария", "nocomment")], _back_row()])


def payment(options: list[PaymentMethod]) -> InlineKeyboardMarkup:
    rows = [[_btn(PAYMENT_TITLES[p], "pay", p)] for p in options]
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm(total: int, online: bool) -> InlineKeyboardMarkup:
    text = f"💳 Перейти к оплате · {money(total)}" if online else f"✅ Подтвердить заказ · {money(total)}"
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(text, "confirm")], _back_row()])


def done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[nav_button("📦 Мои заказы", "orders")], [home_button()]])
