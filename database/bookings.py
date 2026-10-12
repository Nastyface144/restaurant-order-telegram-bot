"""Брони столиков."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime

from utils.timeutil import local_day_bounds_db, now_db, to_db

from .core import db
from .models import Booking, BookingStatus


async def create_booking(*, user_id: int, starts_at: datetime, guests: int, name: str, phone: str) -> int:
    cursor = await db.execute(
        """
        INSERT INTO bookings (user_id, starts_at, guests, name, phone, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, to_db(starts_at), guests, name, phone, str(BookingStatus.PENDING), now_db()),
    )
    return cursor.lastrowid


async def get_booking(booking_id: int) -> Booking | None:
    row = await db.fetchone("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    return Booking.from_row(row) if row else None


async def set_admin_messages(booking_id: int, messages: Iterable[tuple[int, int]]) -> None:
    await db.execute(
        "UPDATE bookings SET admin_messages = ? WHERE id = ?",
        (json.dumps([list(m) for m in messages]), booking_id),
    )


async def update_status(
    booking_id: int, new_status: BookingStatus, *, expected: BookingStatus, decided_by: str | None = None
) -> bool:
    """Условное обновление: если два админа нажали одновременно, сработает только первое."""
    cursor = await db.execute(
        "UPDATE bookings SET status = ?, decided_by = ? WHERE id = ? AND status = ?",
        (str(new_status), decided_by, booking_id, str(expected)),
    )
    return cursor.rowcount > 0


async def get_bookings_for_day(day: date) -> list[Booking]:
    start, end = local_day_bounds_db(day)
    rows = await db.fetchall(
        "SELECT * FROM bookings WHERE starts_at >= ? AND starts_at < ? ORDER BY starts_at",
        (start, end),
    )
    return [Booking.from_row(r) for r in rows]


async def get_user_bookings(user_id: int, after: datetime, limit: int = 5) -> list[Booking]:
    rows = await db.fetchall(
        "SELECT * FROM bookings WHERE user_id = ? AND starts_at >= ? ORDER BY starts_at LIMIT ?",
        (user_id, to_db(after), limit),
    )
    return [Booking.from_row(r) for r in rows]


async def get_upcoming_confirmed(after: datetime) -> list[Booking]:
    rows = await db.fetchall(
        "SELECT * FROM bookings WHERE status = ? AND starts_at > ?",
        (str(BookingStatus.CONFIRMED), to_db(after)),
    )
    return [Booking.from_row(r) for r in rows]
