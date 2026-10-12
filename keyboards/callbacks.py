"""Callback data всех кнопок. Префиксы короткие: лимит Telegram — 64 байта."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class Nav(CallbackData, prefix="nav"):
    """Переход между разделами клиента."""

    to: str  # main | menu | cart | orders | booking | contacts | leave_table
