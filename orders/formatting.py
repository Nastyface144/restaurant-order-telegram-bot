"""Тексты карточек заказа для клиента и персонала."""

from __future__ import annotations

import config
from database.models import Order, OrderMethod, PaymentMethod
from utils.format import esc, format_phone, money
from utils.timeutil import human_datetime, now_local

from .checkout import METHOD_TITLES, PAYMENT_TITLES
from .statuses import status_label

SEPARATOR = "┈┈┈┈┈┈┈┈┈┈┈┈"


def items_block(order: Order) -> list[str]:
    lines = []
    for n, item in enumerate(order.items, 1):
        qty = f" × {item.qty}" if item.qty > 1 else ""
        lines.append(f"{n}. {esc(item.full_title)}{qty} — {money(item.total)}")
    return lines


def when_text(order: Order) -> str:
    if order.method == OrderMethod.TABLE:
        return "Сразу"
    if order.scheduled_at is None:
        return "Как можно скорее"
    return human_datetime(order.scheduled_at, now_local().date()).capitalize()


def payment_text(order: Order) -> str:
    title = PAYMENT_TITLES.get(order.payment_method, str(order.payment_method))
    if order.payment_method == PaymentMethod.ONLINE:
        return f"{title} · {'✅ оплачен' if order.is_paid else '⏳ не оплачен'}"
    return title


def totals_block(order: Order) -> list[str]:
    lines = [f"Товары: {money(order.subtotal)}"]
    if order.method == OrderMethod.DELIVERY:
        zone = config.get_zone(order.zone_id)
        fee = "бесплатно" if order.delivery_fee == 0 else money(order.delivery_fee)
        lines.append(f"Доставка: {fee}" + (f" ({esc(zone.title)})" if zone else ""))
    lines.append(f"<b>Итого: {money(order.total)}</b>")
    return lines


def staff_card(order: Order, customer_username: str | None = None) -> str:
    """Карточка заказа в рабочем чате."""
    head = f"<b>Заказ №{order.id}</b> · {METHOD_TITLES[order.method]}"
    if order.method == OrderMethod.TABLE:
        head += f" · <b>стол №{order.table_no}</b>"
    lines = [
        head,
        f"🕐 <b>{when_text(order)}</b> · оформлен {order.created_at:%H:%M}",
        SEPARATOR,
        *items_block(order),
        SEPARATOR,
        *totals_block(order),
        payment_text(order),
        "",
    ]
    customer = f'👤 <a href="tg://user?id={order.user_id}">{esc(order.customer_name or "Клиент")}</a>'
    if customer_username:
        customer += f" (@{esc(customer_username)})"
    lines.append(customer)
    if order.phone:
        lines.append(f"📞 {format_phone(order.phone)}")
    if order.method == OrderMethod.DELIVERY and order.address:
        lines.append(f"📍 {esc(order.address)}")
    if order.comment:
        lines.append(f"💬 {esc(order.comment)}")
    lines += ["", f"Статус: <b>{status_label(order.status, order.method)}</b>"]
    if order.reject_reason:
        lines.append(f"Причина: {esc(order.reject_reason)}")
    if order.status_changed_by:
        lines.append(f"<i>{esc(order.status_changed_by)}, {order.updated_at:%H:%M}</i>")
    return "\n".join(lines)


def client_card(order: Order) -> str:
    """Заказ в разделе «Мои заказы»."""
    lines = [
        f"🧾 <b>Заказ №{order.id}</b> от {order.created_at:%d.%m %H:%M}",
        f"Статус: <b>{status_label(order.status, order.method)}</b>",
        "",
        *items_block(order),
        "",
        *totals_block(order),
        "",
        METHOD_TITLES[order.method] + (f" · стол №{order.table_no}" if order.method == OrderMethod.TABLE else ""),
    ]
    if order.method == OrderMethod.DELIVERY and order.address:
        lines.append(f"📍 {esc(order.address)}")
    if order.method != OrderMethod.TABLE:
        lines.append(f"🕐 {when_text(order)}")
    lines.append(payment_text(order))
    if order.reject_reason:
        lines.append(f"\nПричина отклонения: {esc(order.reject_reason)}")
    return "\n".join(lines)
