"""Меню: категории, блюда, стоп-лист."""

from __future__ import annotations

from .core import db
from .models import Category, MenuItem


async def get_categories(only_with_available: bool = True) -> list[Category]:
    """Категории по порядку. По умолчанию — только те, где есть что заказать."""
    if only_with_available:
        sql = """
            SELECT c.* FROM categories c
            WHERE EXISTS (SELECT 1 FROM items i WHERE i.category_id = c.id AND i.is_available = 1)
            ORDER BY c.sort, c.id
        """
    else:
        sql = "SELECT * FROM categories ORDER BY sort, id"
    rows = await db.fetchall(sql)
    return [Category(id=r["id"], title=r["title"], emoji=r["emoji"], sort=r["sort"]) for r in rows]


async def get_category(category_id: int) -> Category | None:
    r = await db.fetchone("SELECT * FROM categories WHERE id = ?", (category_id,))
    return Category(id=r["id"], title=r["title"], emoji=r["emoji"], sort=r["sort"]) if r else None


async def get_items(category_id: int, only_available: bool = True) -> list[MenuItem]:
    sql = "SELECT * FROM items WHERE category_id = ?"
    if only_available:
        sql += " AND is_available = 1"
    sql += " ORDER BY sort, id"
    return [MenuItem.from_row(r) for r in await db.fetchall(sql, (category_id,))]


async def get_item(item_id: int) -> MenuItem | None:
    row = await db.fetchone("SELECT * FROM items WHERE id = ?", (item_id,))
    return MenuItem.from_row(row) if row else None


async def get_items_by_ids(item_ids: list[int]) -> dict[int, MenuItem]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" * len(item_ids))
    rows = await db.fetchall(f"SELECT * FROM items WHERE id IN ({placeholders})", item_ids)
    return {r["id"]: MenuItem.from_row(r) for r in rows}


async def toggle_availability(item_id: int) -> bool | None:
    """Переключает «в стоп-листе / в продаже». Возвращает новое значение is_available."""
    await db.execute("UPDATE items SET is_available = 1 - is_available WHERE id = ?", (item_id,))
    value = await db.fetchval("SELECT is_available FROM items WHERE id = ?", (item_id,))
    return None if value is None else bool(value)


async def count_stopped() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM items WHERE is_available = 0") or 0


async def save_photo_file_id(item_id: int, file_id: str) -> None:
    """Кэшируем file_id, чтобы не загружать фото заново при каждом показе."""
    await db.execute("UPDATE items SET photo_file_id = ? WHERE id = ?", (file_id, item_id))


async def is_empty() -> bool:
    return not await db.fetchval("SELECT EXISTS (SELECT 1 FROM items)")


async def count_stopped_by_category() -> dict[int, int]:
    rows = await db.fetchall("SELECT category_id, COUNT(*) AS n FROM items WHERE is_available = 0 GROUP BY category_id")
    return {r["category_id"]: r["n"] for r in rows}
