"""Расчёт сумм: товары, доставка, минимальный заказ."""

from __future__ import annotations

import config
from database.models import CartLine, OrderItem


def available_lines(lines: list[CartLine]) -> list[CartLine]:
    return [line for line in lines if line.item.is_available]


def subtotal(lines: list[CartLine]) -> int:
    """Сумма за товары (позиции из стоп-листа не учитываются)."""
    return sum(line.total for line in available_lines(lines))


def delivery_fee(items_total: int) -> int:
    """Стоимость доставки: фиксированная цена, бесплатно от DELIVERY_FREE_FROM."""
    if config.DELIVERY_FREE_FROM and items_total >= config.DELIVERY_FREE_FROM:
        return 0
    return config.DELIVERY_PRICE


def min_order_shortfall(items_total: int) -> int:
    """Сколько не хватает до минимальной суммы заказа на доставку (0 — хватает)."""
    return max(0, config.DELIVERY_MIN_ORDER - items_total)


def free_delivery_left(items_total: int) -> int:
    """Сколько добавить до бесплатной доставки (0 — уже бесплатно или такой опции нет)."""
    if not config.DELIVERY_FREE_FROM or not config.DELIVERY_PRICE:
        return 0
    return max(0, config.DELIVERY_FREE_FROM - items_total)


def delivery_price_text(fee: int) -> str:
    from utils.format import money

    return "бесплатно" if fee == 0 else money(fee)


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
