"""Статусы заказа: подписи, переходы и тексты уведомлений клиенту."""

from __future__ import annotations

from dataclasses import dataclass

from database.models import OrderMethod, OrderStatus

STATUS_LABELS: dict[OrderStatus, str] = {
    OrderStatus.PENDING_PAYMENT: "⏳ Ждёт оплаты",
    OrderStatus.NEW: "🆕 Новый",
    OrderStatus.ACCEPTED: "✅ Принят",
    OrderStatus.COOKING: "👨‍🍳 Готовится",
    OrderStatus.READY: "🛎 Готов к выдаче",
    OrderStatus.ON_THE_WAY: "🛵 Курьер в пути",
    OrderStatus.COMPLETED: "🎉 Выполнен",
    OrderStatus.REJECTED: "❌ Отклонён",
    OrderStatus.CANCELLED: "🚫 Отменён",
}

ACTIVE_STATUSES = frozenset({
    OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.COOKING, OrderStatus.READY, OrderStatus.ON_THE_WAY,
})
FINAL_STATUSES = frozenset({OrderStatus.COMPLETED, OrderStatus.REJECTED, OrderStatus.CANCELLED})
# Отклонить можно, пока заказ не отдан курьеру / не выдан
REJECTABLE_STATUSES = frozenset({OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.COOKING})


def status_label(status: OrderStatus, method: OrderMethod | None = None) -> str:
    if status == OrderStatus.COMPLETED:
        return {
            OrderMethod.DELIVERY: "🎉 Доставлен",
            OrderMethod.PICKUP: "🎉 Выдан",
            OrderMethod.TABLE: "🎉 Подан",
        }.get(method, STATUS_LABELS[status])
    if status == OrderStatus.READY and method == OrderMethod.TABLE:
        return "🛎 Готов, несём к столу"
    return STATUS_LABELS[status]


@dataclass(frozen=True)
class Transition:
    to: OrderStatus
    button: str  # текст кнопки у персонала


def next_transition(status: OrderStatus, method: OrderMethod) -> Transition | None:
    """Следующий шаг заказа для кнопки в рабочем чате. Цепочки:

    доставка:   новый → принят → готовится → курьер выехал → доставлен
    самовывоз:  новый → принят → готовится → готов к выдаче → выдан
    за столом:  новый → принят → готовится → готов → подан
    """
    if status == OrderStatus.NEW:
        return Transition(OrderStatus.ACCEPTED, "✅ Принять")
    if status == OrderStatus.ACCEPTED:
        return Transition(OrderStatus.COOKING, "👨‍🍳 Готовится")
    if status == OrderStatus.COOKING:
        if method == OrderMethod.DELIVERY:
            return Transition(OrderStatus.ON_THE_WAY, "🛵 Курьер выехал")
        return Transition(OrderStatus.READY, "🛎 Готов к выдаче" if method == OrderMethod.PICKUP else "🛎 Готов")
    if status in (OrderStatus.ON_THE_WAY, OrderStatus.READY):
        label = {OrderMethod.DELIVERY: "🎉 Доставлен", OrderMethod.PICKUP: "🎉 Выдан"}.get(method, "🎉 Подан")
        return Transition(OrderStatus.COMPLETED, label)
    return None


def previous_statuses(target: OrderStatus, method: OrderMethod) -> set[OrderStatus]:
    """Из каких статусов допустим переход в target (для условного UPDATE в БД)."""
    return {s for s in ACTIVE_STATUSES if (t := next_transition(s, method)) and t.to == target}


def client_notification(order_id: int, status: OrderStatus, method: OrderMethod,
                        reason: str | None = None) -> str | None:
    """Текст уведомления клиенту о смене статуса."""
    n = f"№{order_id}"
    if status == OrderStatus.ACCEPTED:
        return f"✅ Заказ {n} принят! Скоро начнём готовить."
    if status == OrderStatus.COOKING:
        return f"👨‍🍳 Заказ {n} готовится."
    if status == OrderStatus.READY:
        if method == OrderMethod.TABLE:
            return f"🛎 Заказ {n} готов — уже несём к вашему столу!"
        return f"🛎 Заказ {n} готов к выдаче! Ждём вас 🙌"
    if status == OrderStatus.ON_THE_WAY:
        return f"🛵 Курьер выехал с заказом {n}. Скоро будет у вас!"
    if status == OrderStatus.COMPLETED:
        if method == OrderMethod.DELIVERY:
            return f"🎉 Заказ {n} доставлен. Приятного аппетита!"
        if method == OrderMethod.PICKUP:
            return f"🎉 Заказ {n} выдан. Приятного аппетита!"
        return "🎉 Приятного аппетита! Будем рады видеть вас снова."
    if status == OrderStatus.REJECTED:
        text = f"😔 К сожалению, заказ {n} отклонён."
        if reason:
            text += f"\nПричина: {reason}"
        return text
    if status == OrderStatus.CANCELLED:
        return f"🚫 Заказ {n} отменён."
    return None
