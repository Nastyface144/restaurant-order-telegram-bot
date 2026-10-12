"""Клавиатуры брони столика."""

from __future__ import annotations

from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database.models import Booking, BookingStatus
from utils.format import format_phone, truncate
from utils.timeutil import WEEKDAYS_SHORT, human_date

from .callbacks import BookAdminCb, BookCb
from .common import BACK, home_button


def _btn(text: str, a: str, v: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=BookCb(a=a, v=v).pack())


def _day_label(day: date, today: date) -> str:
    if (day - today).days in (0, 1):
        return human_date(day, today).capitalize()
    return f"{WEEKDAYS_SHORT[day.weekday()].capitalize()}, {day:%d.%m}"  # коротко — кнопки в 3 колонки


def dates(days: list[date], today: date) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for day in days:
        kb.add(_btn(_day_label(day, today), "date", f"{day:%Y%m%d}"))
    kb.adjust(3)
    kb.row(home_button())
    return kb.as_markup()


def times(slots: list[datetime]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for slot in slots:
        kb.add(_btn(f"{slot:%H:%M}", "time", f"{slot:%H%M}"))
    kb.adjust(4)
    kb.row(_btn(BACK, "back"))
    return kb.as_markup()


def guests() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in range(1, config.BOOKING_MAX_GUESTS + 1):
        kb.add(_btn(str(n), "guests", str(n)))
    kb.adjust(4)
    kb.row(_btn(BACK, "back"))
    return kb.as_markup()


def name(suggested: str | None) -> InlineKeyboardMarkup:
    rows = []
    if suggested:
        rows.append([_btn(f"👤 {truncate(suggested, 30)}", "name")])
    rows.append([_btn(BACK, "back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def phone(saved: str | None) -> InlineKeyboardMarkup:
    rows = []
    if saved:
        rows.append([_btn(f"📞 {format_phone(saved)}", "phone")])
    rows.append([_btn(BACK, "back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Отправить заявку", "confirm")],
        [_btn(BACK, "back")],
    ])


def done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[home_button()]])


def admin_decision(booking: Booking) -> InlineKeyboardMarkup | None:
    if booking.status != BookingStatus.PENDING:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=BookAdminCb(a="ok", id=booking.id).pack()),
        InlineKeyboardButton(text="❌ Нет мест", callback_data=BookAdminCb(a="no", id=booking.id).pack()),
    ]])
