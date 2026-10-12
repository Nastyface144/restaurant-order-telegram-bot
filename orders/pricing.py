"""Расчёт сумм: товары, доставка по зоне, минимальный заказ."""

from __future__ import annotations

from config import DeliveryZone
from database.models import CartLine, OrderItem


def available_lines(lines: list[CartLine]) -> list[CartLine]:
    return [l for l in lines if l.item.is_available]


def subtotal(lines: list[CartLine]) -> int:
    """Сумма за товары (позиции из стоп-листа не учитываются)."""
    return sum(l.total for l in available_lines(lines))


def delivery_fee(zone: DeliveryZone, items_total: int) -> int:
    if zone.free_from and items_total >= zone.free_from:
        return 0
    return zone.price


def min_order_shortfall(zone: DeliveryZone, items_total: int) -> int:
    """Сколько не хватает до минимальной суммы заказа в зоне (0 — хватает)."""
    return max(0, zone.min_order - items_total)


def line_title(line: CartLine) -> str:
    """«Пепперони, 35 см + Бекон, Халапеньо»."""
    title = line.item.title
    if line.size and len(line.item.sizes) > 1:
        title += f", {line.size.title}"
    if line.addons:
        title += " + " + ", ".join(a.title for a in line.addons)
    return title


def to_order_items(lines: list[CartLine]) -> list[OrderItem]:
    """Снимок позиций корзины для заказа: названия и цены фиксируются на момент оформления."""
    return [
        OrderItem(
            item_id=l.item.id,
            title=l.item.title,
            size_code=l.size_code,
            size_title=l.size.title if l.size and len(l.item.sizes) > 1 else "",
            addon_codes=tuple(a.code for a in l.addons),
            addons_title=", ".join(a.title for a in l.addons),
            unit_price=l.unit_price,
            qty=l.qty,
        )
        for l in available_lines(lines)
    ]
