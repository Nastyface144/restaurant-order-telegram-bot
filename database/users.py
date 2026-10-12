"""Клиенты бота."""

from __future__ import annotations

from utils.timeutil import now_db

from .core import db
from .models import User


async def upsert_user(user_id: int, full_name: str, username: str | None) -> None:
    """Регистрирует пользователя или обновляет имя. Если он раньше блокировал бота — снимает флаг."""
    await db.execute(
        """
        INSERT INTO users (id, full_name, username, created_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            full_name = excluded.full_name,
            username = excluded.username,
            is_blocked = 0
        """,
        (user_id, full_name, username, now_db()),
    )


async def get_user(user_id: int) -> User | None:
    row = await db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
    return User.from_row(row) if row else None


async def save_contact_details(
    user_id: int, phone: str | None = None, address: str | None = None, zone_id: int | None = None
) -> None:
    """Запоминаем телефон и адрес, чтобы в следующий раз предложить их одной кнопкой."""
    await db.execute(
        """
        UPDATE users SET
            phone = COALESCE(?, phone),
            last_address = COALESCE(?, last_address),
            last_zone_id = COALESCE(?, last_zone_id)
        WHERE id = ?
        """,
        (phone, address, zone_id, user_id),
    )


async def set_table(user_id: int, table_no: int | None) -> None:
    await db.execute(
        "UPDATE users SET table_no = ?, table_set_at = ? WHERE id = ?",
        (table_no, now_db() if table_no else None, user_id),
    )


async def mark_blocked(user_id: int) -> None:
    await db.execute("UPDATE users SET is_blocked = 1 WHERE id = ?", (user_id,))


async def get_active_user_ids() -> list[int]:
    rows = await db.fetchall("SELECT id FROM users WHERE is_blocked = 0 ORDER BY id")
    return [r["id"] for r in rows]


async def count_users() -> tuple[int, int]:
    """(всего, активных)."""
    row = await db.fetchone("SELECT COUNT(*), COALESCE(SUM(is_blocked = 0), 0) FROM users")
    return row[0], row[1]
