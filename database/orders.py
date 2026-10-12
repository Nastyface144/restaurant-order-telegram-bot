"""Заказы."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from utils.timeutil import local_day_bounds_db, now_db, to_db

from .core import db
from .models import Order, OrderItem, OrderMethod, OrderStatus, PaymentMethod

# Статусы, которые считаются в выручку и статистику (заказ реально в работе или выполнен)
COUNTED_STATUSES = (
    OrderStatus.NEW,
    OrderStatus.ACCEPTED,
    OrderStatus.COOKING,
    OrderStatus.READY,
    OrderStatus.ON_THE_WAY,
    OrderStatus.COMPLETED,
)


def _in(statuses: Iterable[OrderStatus]) -> tuple[str, list[str]]:
    values = [str(s) for s in statuses]
    return ",".join("?" * len(values)), values


async def create_order(
    *,
    user_id: int,
    status: OrderStatus,
    method: OrderMethod,
    customer_name: str,
    phone: str | None,
    payment_method: PaymentMethod,
    items: list[OrderItem],
    delivery_fee: int = 0,
    zone_id: int | None = None,
    address: str | None = None,
    table_no: int | None = None,
    comment: str | None = None,
    scheduled_at: datetime | None = None,
    clear_cart: bool = True,
) -> int:
    """Создаёт заказ с позициями и (по умолчанию) очищает корзину — одной транзакцией."""
    if not items:
        raise ValueError("Нельзя создать пустой заказ")
    subtotal = sum(i.total for i in items)
    now = now_db()
    async with db.transaction() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO orders (user_id, status, method, zone_id, address, table_no, customer_name, phone,
                                comment, scheduled_at, payment_method, subtotal, delivery_fee, total,
                                created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, str(status), str(method), zone_id, address, table_no, customer_name, phone,
                comment, to_db(scheduled_at) if scheduled_at else None, str(payment_method),
                subtotal, delivery_fee, subtotal + delivery_fee, now, now,
            ),
        )
        order_id = cursor.lastrowid
        await conn.executemany(
            """
            INSERT INTO order_items (order_id, item_id, title, size_code, size_title,
                                     addon_codes, addons_title, unit_price, qty)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (order_id, i.item_id, i.title, i.size_code, i.size_title,
                 ",".join(i.addon_codes), i.addons_title, i.unit_price, i.qty)
                for i in items
            ],
        )
        if clear_cart:
            await conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    return order_id


async def _attach_items(rows) -> list[Order]:
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    placeholders = ",".join("?" * len(ids))
    item_rows = await db.fetchall(
        f"SELECT * FROM order_items WHERE order_id IN ({placeholders}) ORDER BY id", ids
    )
    by_order: dict[int, list[OrderItem]] = {}
    for r in item_rows:
        by_order.setdefault(r["order_id"], []).append(OrderItem.from_row(r))
    return [Order.from_row(r, tuple(by_order.get(r["id"], ()))) for r in rows]


async def get_order(order_id: int) -> Order | None:
    row = await db.fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if row is None:
        return None
    return (await _attach_items([row]))[0]


# Заказы, которые так и не дошли до заведения (не оплачены онлайн), в истории и статистике не показываем
HIDDEN_STATUSES = (str(OrderStatus.PENDING_PAYMENT), str(OrderStatus.CANCELLED))


async def get_user_orders(user_id: int, limit: int = 10) -> list[Order]:
    """Последние заказы клиента."""
    rows = await db.fetchall(
        "SELECT * FROM orders WHERE user_id = ? AND status NOT IN (?, ?) ORDER BY id DESC LIMIT ?",
        (user_id, *HIDDEN_STATUSES, limit),
    )
    return await _attach_items(rows)


async def update_status(
    order_id: int,
    new_status: OrderStatus,
    *,
    expected: Iterable[OrderStatus],
    changed_by: str | None = None,
    reject_reason: str | None = None,
) -> bool:
    """Меняет статус, только если текущий входит в expected.

    Так два сотрудника, одновременно нажавшие кнопку, не «перепрыгнут» через статус:
    второе нажатие просто вернёт False.
    """
    placeholders, values = _in(expected)
    cursor = await db.execute(
        f"""
        UPDATE orders SET status = ?, status_changed_by = ?, updated_at = ?,
                          reject_reason = COALESCE(?, reject_reason)
        WHERE id = ? AND status IN ({placeholders})
        """,
        (str(new_status), changed_by, now_db(), reject_reason, order_id, *values),
    )
    return cursor.rowcount > 0


async def mark_paid(order_id: int, telegram_charge_id: str, provider_charge_id: str) -> bool:
    """Онлайн-оплата прошла: заказ становится новым и уходит персоналу.

    Заказ мог успеть отмениться по таймауту неоплаты ровно в момент оплаты —
    деньги уже списаны, поэтому такой заказ тоже «оживляем».
    """
    cursor = await db.execute(
        """
        UPDATE orders SET is_paid = 1, status = ?, telegram_charge_id = ?, provider_charge_id = ?,
                          updated_at = ?
        WHERE id = ? AND is_paid = 0 AND status IN (?, ?)
        """,
        (str(OrderStatus.NEW), telegram_charge_id, provider_charge_id, now_db(),
         order_id, str(OrderStatus.PENDING_PAYMENT), str(OrderStatus.CANCELLED)),
    )
    return cursor.rowcount > 0


async def mark_paid_on_receipt(order_id: int) -> None:
    """Оплата наличными/картой считается полученной, когда заказ выдан."""
    await db.execute("UPDATE orders SET is_paid = 1 WHERE id = ?", (order_id,))


async def set_staff_message(order_id: int, message_id: int) -> None:
    await db.execute("UPDATE orders SET staff_message_id = ? WHERE id = ?", (message_id, order_id))


async def get_orders_for_day(day: date) -> list[Order]:
    """Все заказы за локальные сутки, дошедшие до заведения."""
    start, end = local_day_bounds_db(day)
    rows = await db.fetchall(
        "SELECT * FROM orders WHERE created_at >= ? AND created_at < ? AND status NOT IN (?, ?) ORDER BY id",
        (start, end, *HIDDEN_STATUSES),
    )
    return await _attach_items(rows)


async def get_stale_unpaid(older_than: datetime) -> list[int]:
    rows = await db.fetchall(
        "SELECT id FROM orders WHERE status = ? AND created_at < ?",
        (str(OrderStatus.PENDING_PAYMENT), to_db(older_than)),
    )
    return [r["id"] for r in rows]


async def get_upcoming_scheduled(after: datetime) -> list[Order]:
    """Активные заказы «ко времени», время которых ещё не наступило (для планировщика)."""
    placeholders, values = _in(COUNTED_STATUSES[:-1])  # без выполненных
    rows = await db.fetchall(
        f"SELECT * FROM orders WHERE scheduled_at IS NOT NULL AND scheduled_at > ? AND status IN ({placeholders})",
        (to_db(after), *values),
    )
    return await _attach_items(rows)
