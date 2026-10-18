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


# Этапы трекера заказа для клиента: (статус, эмодзи текущего этапа, подпись)
TRACKER_STAGES: dict[OrderMethod, tuple[tuple[OrderStatus, str, str], ...]] = {
    OrderMethod.DELIVERY: (
        (OrderStatus.ACCEPTED, "✅", "Заказ принят"),
        (OrderStatus.COOKING, "👨‍🍳", "Готовим"),
        (OrderStatus.ON_THE_WAY, "🛵", "Курьер в пути"),
        (OrderStatus.COMPLETED, "🎉", "Доставлен"),
    ),
    OrderMethod.PICKUP: (
        (OrderStatus.ACCEPTED, "✅", "Заказ принят"),
        (OrderStatus.COOKING, "👨‍🍳", "Готовим"),
        (OrderStatus.READY, "🛎", "Готов — можно забирать"),
        (OrderStatus.COMPLETED, "🎉", "Выдан"),
    ),
    OrderMethod.TABLE: (
        (OrderStatus.ACCEPTED, "✅", "Заказ принят"),
        (OrderStatus.COOKING, "👨‍🍳", "Готовим"),
        (OrderStatus.READY, "🛎", "Несём к столу"),
        (OrderStatus.COMPLETED, "🎉", "Приятного аппетита"),
    ),
}

SHORT_STATUS = {
    OrderStatus.PENDING_PAYMENT: "ждёт оплаты",
    OrderStatus.NEW: "ждёт подтверждения",
    OrderStatus.ACCEPTED: "принят",
    OrderStatus.COOKING: "готовим",
    OrderStatus.READY: "готов",
    OrderStatus.ON_THE_WAY: "в пути",
    OrderStatus.COMPLETED: "выполнен",
    OrderStatus.REJECTED: "отклонён",
    OrderStatus.CANCELLED: "отменён",
}


def short_status(order) -> str:
    if order.status == OrderStatus.READY and order.method == OrderMethod.TABLE:
        return "несём к столу"
    if order.status == OrderStatus.READY:
        return "можно забирать"
    return SHORT_STATUS[order.status]


def tracker(status: OrderStatus, method: OrderMethod) -> str:
    """Прогресс заказа столбиком: пройденные этапы — ✅, текущий — жирным, будущие — ⚪️."""
    stages = TRACKER_STAGES[method]
    order_of = [stage[0] for stage in stages]
    current = order_of.index(status) if status in order_of else -1
    lines = []
    if status == OrderStatus.NEW:
        lines.append("⏳ <b>Ждём подтверждения заведения</b>")
    for index, (_, icon, label) in enumerate(stages):
        if index < current:
            lines.append(f"✅ {label}")
        elif index == current:
            lines.append(f"{icon} <b>{label}</b>")
        else:
            lines.append(f"⚪️ {label}")
    return "<blockquote>" + "\n".join(lines) + "</blockquote>"


def client_notification(order_id: int, status: OrderStatus, method: OrderMethod,
                        reason: str | None = None) -> str | None:
    """Уведомление клиенту о смене статуса: заголовок, одна строка пояснения и трекер."""
    n = f"№{order_id}"
    heads = {
        OrderStatus.ACCEPTED: ("✅ <b>Заказ принят!</b>", f"Заказ {n} уже у нас — скоро начнём готовить."),
        OrderStatus.COOKING: ("👨‍🍳 <b>Готовим ваш заказ</b>", f"Заказ {n} на кухне."),
        OrderStatus.ON_THE_WAY: ("🛵 <b>Курьер выехал!</b>", f"Заказ {n} скоро будет у вас."),
    }
    if status == OrderStatus.READY:
        heads[status] = (
            ("🛎 <b>Несём к вашему столу!</b>", f"Заказ {n} готов.") if method == OrderMethod.TABLE
            else ("🛎 <b>Заказ готов!</b>", f"Заказ {n} ждёт вас — можно забирать 🙌")
        )
    if status == OrderStatus.COMPLETED:
        line = {
            OrderMethod.DELIVERY: f"Заказ {n} доставлен.",
            OrderMethod.PICKUP: f"Заказ {n} выдан.",
        }.get(method, "Будем рады видеть вас снова.")
        heads[status] = ("🎉 <b>Приятного аппетита!</b>", line)
    if status in heads:
        head, line = heads[status]
        return f"{head}\n{line}\n\n{tracker(status, method)}"
    if status == OrderStatus.REJECTED:
        text = f"😔 <b>Заказ {n} отклонён</b>"
        if reason:
            text += f"\nПричина: {reason}"
        return text
    if status == OrderStatus.CANCELLED:
        return f"🚫 <b>Заказ {n} отменён</b>"
    return None
