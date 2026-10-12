"""«Повторить заказ»: положить позиции старого заказа в корзину по актуальным ценам."""

from __future__ import annotations

from dataclasses import dataclass, field

from database import cart, menu
from database.models import Order


@dataclass
class RepeatResult:
    added: int = 0
    unavailable: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)  # добавлено, но без части добавок


async def repeat_order(user_id: int, order: Order) -> RepeatResult:
    result = RepeatResult()
    items = await menu.get_items_by_ids([i.item_id for i in order.items])
    for old in order.items:
        item = items.get(old.item_id)
        if item is None or not item.is_available:
            result.unavailable.append(old.title)
            continue
        if item.sizes and item.get_size(old.size_code) is None:
            # Размер убрали из меню — не угадываем, сообщаем клиенту
            result.unavailable.append(old.full_title)
            continue
        addons = [a.code for a in item.get_addons(old.addon_codes)]
        if len(addons) != len(old.addon_codes):
            result.changed.append(old.title)
        await cart.add_to_cart(user_id, item.id, old.size_code if item.sizes else "", addons, old.qty)
        result.added += old.qty
    return result
