"""Расчёт сумм: товары, доставка по зоне, минимальный заказ."""

from __future__ import annotations

from config import DeliveryZone
from database.models import CartLine, OrderItem


def available_lines(lines: list[CartLine]) -> list[CartLine]:
    return [line for line in lines if line.item.is_available]


def subtotal(lines: list[CartLine]) -> int:
    """Сумма за товары (позиции из стоп-листа не учитываются)."""
    return sum(line.total for line in available_lines(lines))


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
            item_id=line.item.id,
            title=line.item.title,
            size_code=line.size_code,
            size_title=line.size.title if line.size and len(line.item.sizes) > 1 else "",
            addon_codes=tuple(a.code for a in line.addons),
            addons_title=", ".join(a.title for a in line.addons),
            unit_price=line.unit_price,
            qty=line.qty,
        )
        for line in available_lines(lines)
    ]
