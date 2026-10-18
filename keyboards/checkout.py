"""Клавиатуры оформления заказа."""

from __future__ import annotations

from datetime import date, datetime

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database.models import OrderMethod, PaymentMethod
from orders import pricing
from orders.checkout import METHOD_TITLES, PAYMENT_TITLES, TIME_ASAP, slot_value
from utils.format import format_phone, money, truncate
from utils.timeutil import human_date

from .callbacks import CheckoutCb, OrdersCb
from .common import BACK, PRIMARY, SUCCESS, button, home_button


def _btn(text: str, a: str, v: str = "", style: ButtonStyle | None = None) -> InlineKeyboardButton:
    return button(text, CheckoutCb(a=a, v=v).pack(), style=style)


def _back_row() -> list[InlineKeyboardButton]:
    return [_btn(BACK, "back")]


def _method_label(method: OrderMethod) -> str:
    if method == OrderMethod.DELIVERY and config.DELIVERY_ZONES:
        eta = min(z.eta_minutes for z in config.DELIVERY_ZONES)
        return f"{METHOD_TITLES[method]} · от {eta} мин"
    if method == OrderMethod.PICKUP:
        return f"{METHOD_TITLES[method]} · от {config.PICKUP_LEAD_MINUTES} мин"
    return METHOD_TITLES[method]


def methods(options: list[OrderMethod]) -> InlineKeyboardMarkup:
    rows = [[_btn(_method_label(m), "method", m)] for m in options]
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
        rows.append([_btn(f"📍 {truncate(saved, 40)}", "addr", style=PRIMARY)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_delivery(asap: bool, eta: int | None) -> InlineKeyboardMarkup:
    rows = []
    if asap:
        rows.append([_btn("⚡ Как можно скорее" + (f" · ≈{eta} мин" if eta else ""), "time", TIME_ASAP,
                          style=PRIMARY)])
    rows.append([_btn("🕐 Ко времени", "slots")])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_pickup(quick: list[int]) -> InlineKeyboardMarkup:
    rows = []
    if quick:
        rows.append([_btn(f"Через {m} мин", "time", f"in_{m}", style=PRIMARY if i == 0 else None)
                     for i, m in enumerate(quick)])
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
            kb.row(button(f"📅 {human_date(current_day, today).capitalize()}", "noop"))
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
        rows.append([_btn(f"📞 {format_phone(saved)}", "phone", style=PRIMARY)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def comment() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Без комментария →", "nocomment", style=PRIMARY)],
                                                 _back_row()])


def payment(options: list[PaymentMethod]) -> InlineKeyboardMarkup:
    rows = [[_btn(PAYMENT_TITLES[p], "pay", p)] for p in options]
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm(total: int, online: bool) -> InlineKeyboardMarkup:
    text = f"💳 Перейти к оплате · {money(total)}" if online else f"✅ Подтвердить заказ · {money(total)}"
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(text, "confirm", style=SUCCESS)], _back_row()])


def done(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("📦 Следить за заказом", OrdersCb(a="view", id=order_id).pack(), style=PRIMARY)],
        [home_button()],
    ])
