"""Корзина хранится в БД, поэтому переживает перезапуск бота."""

from __future__ import annotations

from .core import db
from .menu import get_items_by_ids
from .models import CartLine

MAX_QTY = 50


def _addons_key(addon_codes: list[str] | tuple[str, ...]) -> str:
    return ",".join(sorted(set(addon_codes)))


async def add_to_cart(
    user_id: int, item_id: int, size_code: str, addon_codes: list[str] | tuple[str, ...], qty: int = 1
) -> None:
    """Добавляет позицию; одинаковые (то же блюдо, размер и добавки) складываются."""
    await db.execute(
        f"""
        INSERT INTO cart_items (user_id, item_id, size_code, addon_codes, qty) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, item_id, size_code, addon_codes)
        DO UPDATE SET qty = MIN(qty + excluded.qty, {MAX_QTY})
        """,
        (user_id, item_id, size_code or "", _addons_key(addon_codes), max(1, min(qty, MAX_QTY))),
    )


async def get_cart(user_id: int) -> list[CartLine]:
    """Позиции корзины. Удалённые из меню блюда тихо пропадают (FK cascade)."""
    rows = await db.fetchall("SELECT * FROM cart_items WHERE user_id = ? ORDER BY id", (user_id,))
    items = await get_items_by_ids(list({r["item_id"] for r in rows}))
    lines = []
    for r in rows:
        item = items.get(r["item_id"])
        if item is None:
            continue
        lines.append(
            CartLine(
                id=r["id"],
                item=item,
                size_code=r["size_code"],
                addon_codes=tuple(c for c in r["addon_codes"].split(",") if c),
                qty=r["qty"],
            )
        )
    return lines


async def change_qty(user_id: int, line_id: int, delta: int) -> None:
    """Меняет количество; при нуле позиция удаляется."""
    async with db.transaction() as conn:
        # Сначала удаление, иначе оно сработало бы уже по обновлённому количеству
        await conn.execute(
            "DELETE FROM cart_items WHERE id = ? AND user_id = ? AND qty + ? <= 0",
            (line_id, user_id, delta),
        )
        await conn.execute(
            f"UPDATE cart_items SET qty = MIN(qty + ?, {MAX_QTY}) WHERE id = ? AND user_id = ?",
            (delta, line_id, user_id),
        )


async def remove_line(user_id: int, line_id: int) -> None:
    await db.execute("DELETE FROM cart_items WHERE id = ? AND user_id = ?", (line_id, user_id))


async def clear_cart(user_id: int) -> None:
    await db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))


async def count_cart_items(user_id: int) -> int:
    return await db.fetchval(
        """SELECT COALESCE(SUM(c.qty), 0) FROM cart_items c
           JOIN items i ON i.id = c.item_id WHERE c.user_id = ?""",
        (user_id,),
    ) or 0


async def cart_summary(user_id: int) -> tuple[int, int]:
    """(сколько штук, на какую сумму) — только то, что сейчас есть в продаже."""
    lines = [line for line in await get_cart(user_id) if line.item.is_available]
    return sum(line.qty for line in lines), sum(line.total for line in lines)
