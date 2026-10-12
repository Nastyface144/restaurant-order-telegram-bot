"""Режим «заказ за столиком»: гость сканирует QR-код со ссылкой t.me/<bot>?start=table_N."""

from __future__ import annotations

import re
from datetime import timedelta

import config
from database import users
from database.models import User
from utils.timeutil import now_local

_PAYLOAD_RE = re.compile(r"^table_(\d{1,4})$")


def parse_table_payload(payload: str | None) -> int | None:
    """«table_5» → 5. Неверный формат или номер вне диапазона → None."""
    if not payload:
        return None
    match = _PAYLOAD_RE.match(payload.strip())
    if not match:
        return None
    number = int(match.group(1))
    return number if 1 <= number <= config.TABLES_COUNT else None


def active_table(user: User | None) -> int | None:
    """Номер стола, если гость отсканировал QR недавно (сессия ограничена по времени)."""
    if not config.FEATURES.table or user is None or not user.table_no or not user.table_set_at:
        return None
    if now_local() - user.table_set_at > timedelta(hours=config.TABLE_SESSION_HOURS):
        return None
    return user.table_no


async def get_active_table(user_id: int) -> int | None:
    return active_table(await users.get_user(user_id))


def table_link(bot_username: str, table_no: int) -> str:
    return f"https://t.me/{bot_username}?start=table_{table_no}"
