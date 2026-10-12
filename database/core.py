"""Подключение к SQLite и схема БД."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,           -- Telegram user id
    full_name     TEXT    NOT NULL DEFAULT '',
    username      TEXT,
    phone         TEXT,
    last_address  TEXT,
    last_zone_id  INTEGER,
    table_no      INTEGER,                       -- стол, если гость пришёл по QR-коду
    table_set_at  TEXT,
    is_blocked    INTEGER NOT NULL DEFAULT 0,    -- пользователь заблокировал бота
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    title  TEXT    NOT NULL,
    emoji  TEXT    NOT NULL DEFAULT '',
    sort   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id   INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    title         TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    price         INTEGER NOT NULL DEFAULT 0,
    photo         TEXT,
    photo_file_id TEXT,
    sizes         TEXT    NOT NULL DEFAULT '[]',  -- JSON: [{code, title, price}]
    addons        TEXT    NOT NULL DEFAULT '[]',  -- JSON: [{code, title, price}]
    is_available  INTEGER NOT NULL DEFAULT 1,     -- 0 — в стоп-листе
    sort          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category_id, sort);

CREATE TABLE IF NOT EXISTS cart_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    size_code   TEXT    NOT NULL DEFAULT '',
    addon_codes TEXT    NOT NULL DEFAULT '',      -- коды через запятую, отсортированы
    qty         INTEGER NOT NULL CHECK (qty > 0),
    UNIQUE (user_id, item_id, size_code, addon_codes)
);

CREATE TABLE IF NOT EXISTS orders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL,
    status            TEXT    NOT NULL,
    method            TEXT    NOT NULL,
    zone_id           INTEGER,
    address           TEXT,
    table_no          INTEGER,
    customer_name     TEXT    NOT NULL DEFAULT '',
    phone             TEXT,
    comment           TEXT,
    scheduled_at      TEXT,                       -- NULL — «как можно скорее»
    payment_method    TEXT    NOT NULL,
    is_paid           INTEGER NOT NULL DEFAULT 0,
    subtotal          INTEGER NOT NULL,
    delivery_fee      INTEGER NOT NULL DEFAULT 0,
    total             INTEGER NOT NULL,
    reject_reason     TEXT,
    staff_message_id  INTEGER,
    status_changed_by TEXT,
    telegram_charge_id TEXT,
    provider_charge_id TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL,                -- без FK: блюдо могут удалить из меню
    title        TEXT    NOT NULL,                -- снимок на момент заказа
    size_code    TEXT    NOT NULL DEFAULT '',
    size_title   TEXT    NOT NULL DEFAULT '',
    addon_codes  TEXT    NOT NULL DEFAULT '',
    addons_title TEXT    NOT NULL DEFAULT '',
    unit_price   INTEGER NOT NULL,
    qty          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);

CREATE TABLE IF NOT EXISTS bookings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    starts_at      TEXT    NOT NULL,
    guests         INTEGER NOT NULL,
    name           TEXT    NOT NULL,
    phone          TEXT    NOT NULL,
    status         TEXT    NOT NULL,
    admin_messages TEXT    NOT NULL DEFAULT '[]',  -- JSON: [[chat_id, message_id], ...]
    decided_by     TEXT,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_starts ON bookings(starts_at);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id, id DESC);
"""


class Database:
    """Одно соединение aiosqlite на всё приложение.

    Записи идут через блокировку: так многошаговые транзакции (создание заказа
    с позициями и очисткой корзины) не перемешиваются между корутинами.
    """

    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не подключена — вызовите db.connect()")
        return self._conn

    async def connect(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("База данных подключена: %s", path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, tuple(params)) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, tuple(params)) as cursor:
            return list(await cursor.fetchall())

    async def fetchval(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = await self.fetchone(sql, params)
        return row[0] if row is not None else None

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Cursor:
        """Одиночная запись с коммитом. Возвращает курсор (lastrowid, rowcount)."""
        async with self._lock:
            try:
                cursor = await self.conn.execute(sql, tuple(params))
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise
            return cursor

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Несколько запросов атомарно: коммит в конце или откат при ошибке."""
        async with self._lock:
            try:
                yield self.conn
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise


db = Database()
