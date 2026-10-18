"""Логика оформления заказа, не зависящая от Telegram: шаги, время, проверки.

Порядок шагов: способ получения → данные (зона, адрес, время, телефон) →
комментарий → оплата → подтверждение. Ненужные шаги пропускаются: например,
за столиком остаются только комментарий и подтверждение.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta

import config
from database.models import OrderMethod, PaymentMethod
from utils.timeutil import human_datetime, now_local

from . import hours

TIME_ASAP = "asap"
COMMENT_MAX = 300
ADDRESS_MIN, ADDRESS_MAX = 5, 200


@dataclass
class Draft:
    """Черновик заказа — хранится в FSM пока клиент проходит шаги."""

    method: str | None = None
    address: str | None = None
    time: str | None = None      # "asap" | "in_15" | "at_202610121930"
    phone: str | None = None
    comment: str | None = None
    comment_done: bool = False   # шаг комментария пройден (комментарий может быть пустым)
    payment: str | None = None
    table_no: int | None = None
    step: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> Draft:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})


def available_methods() -> list[OrderMethod]:
    methods = []
    if config.FEATURES.delivery:
        methods.append(OrderMethod.DELIVERY)
    if config.FEATURES.pickup:
        methods.append(OrderMethod.PICKUP)
    return methods


def payment_options(method: str | None) -> list[PaymentMethod]:
    if method == OrderMethod.TABLE:
        return [PaymentMethod.ON_SITE]
    options = []
    if config.FEATURES.online_payment:
        options.append(PaymentMethod.ONLINE)
    if config.FEATURES.cash_payment:
        options.append(PaymentMethod.CASH)
    if config.FEATURES.card_on_receipt:
        options.append(PaymentMethod.CARD)
    return options


def steps(draft: Draft) -> list[str]:
    if draft.method == OrderMethod.TABLE:
        return ["comment", "confirm"]
    result = ["method"] if len(available_methods()) > 1 else []
    if draft.method == OrderMethod.DELIVERY:
        result += ["address", "time", "phone"]
    elif draft.method == OrderMethod.PICKUP:
        result += ["time", "phone"]
    else:
        return result or ["method"]
    result.append("comment")
    if len(payment_options(draft.method)) > 1:
        result.append("payment")
    result.append("confirm")
    return result


def start(table_no: int | None) -> Draft:
    """Новый черновик. Если способ получения один — он выбирается сам."""
    if table_no:
        draft = Draft(method=OrderMethod.TABLE, table_no=table_no, payment=PaymentMethod.ON_SITE)
    else:
        methods = available_methods()
        draft = Draft()
        if len(methods) == 1:
            set_method(draft, methods[0])
        _autofill_payment(draft)
    draft.step = steps(draft)[0]
    return draft


def set_method(draft: Draft, method: OrderMethod) -> None:
    draft.method = method
    draft.time = None  # варианты времени у доставки и самовывоза разные
    _autofill_payment(draft)


def _autofill_payment(draft: Draft) -> None:
    options = payment_options(draft.method)
    if len(options) == 1:
        draft.payment = options[0]
    elif draft.payment not in options:
        draft.payment = None


def is_filled(draft: Draft, step: str) -> bool:
    return {
        "method": draft.method is not None,
        "address": bool(draft.address),
        "time": bool(draft.time),
        "phone": bool(draft.phone),
        "comment": draft.comment_done,
        "payment": draft.payment in payment_options(draft.method),
    }.get(step, False)


def advance(draft: Draft) -> str:
    """Шаг после текущего: первый незаполненный (или подтверждение).

    Так после правки, например, телефона с экрана подтверждения клиент сразу
    возвращается к подтверждению, а не проходит все шаги заново.
    """
    seq = steps(draft)
    start_index = seq.index(draft.step) + 1 if draft.step in seq else 0
    for step in seq[start_index:]:
        if not is_filled(draft, step):
            return step
    return seq[-1]


def prev_step(draft: Draft) -> str | None:
    """Предыдущий шаг или None — тогда «Назад» ведёт в корзину."""
    seq = steps(draft)
    if draft.step not in seq:
        return None
    index = seq.index(draft.step)
    return seq[index - 1] if index > 0 else None


# ---------------------------------------------------------------------------
# Время
# ---------------------------------------------------------------------------

def lead_minutes(method: str | None) -> int:
    return config.DELIVERY_LEAD_MINUTES if method == OrderMethod.DELIVERY else config.PICKUP_LEAD_MINUTES


def slot_value(dt: datetime) -> str:
    return f"at_{dt:%Y%m%d%H%M}"


def parse_time(value: str | None, now: datetime | None = None) -> datetime | None:
    """Время, на которое оформлен заказ. None — «как можно скорее»."""
    now = now or now_local()
    if not value or value == TIME_ASAP:
        return None
    kind, _, raw = value.partition("_")
    if kind == "in":
        return (now + timedelta(minutes=int(raw))).replace(second=0, microsecond=0)
    if kind == "at":
        return datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=config.TIMEZONE)
    raise ValueError(f"Неизвестный формат времени: {value}")


def quick_pickup_options(now: datetime | None = None) -> list[int]:
    """«Через 15 / 30 / 60 минут» — только если к этому времени ещё открыто."""
    now = now or now_local()
    if not hours.accepts_orders_now(now):
        return []
    interval = hours.current_interval(now)
    limit = interval[1] - timedelta(minutes=config.LAST_ORDER_BEFORE_CLOSE_MINUTES)
    return [m for m in config.PICKUP_QUICK_OPTIONS if now + timedelta(minutes=m) <= limit]


def asap_available(now: datetime | None = None) -> bool:
    return hours.accepts_orders_now(now)


def time_label(draft: Draft, now: datetime | None = None) -> str:
    now = now or now_local()
    if not draft.time:
        return "—"
    if draft.time == TIME_ASAP:
        eta = f" (≈{config.DELIVERY_ETA_MINUTES} мин)" if draft.method == OrderMethod.DELIVERY else ""
        return f"Как можно скорее{eta}"
    if draft.time.startswith("in_"):
        minutes = int(draft.time[3:])
        return f"Через {minutes} минут (к {parse_time(draft.time, now):%H:%M})"
    return human_datetime(parse_time(draft.time, now), now.date()).capitalize()


def validate_time(draft: Draft, now: datetime | None = None) -> str | None:
    """Проверка перед созданием заказа. Возвращает текст ошибки или None."""
    now = now or now_local()
    if draft.method == OrderMethod.TABLE:
        return None if hours.is_open(now) else "Сейчас мы закрыты — заказ за столиком недоступен."
    if not draft.time:
        return "Выберите время."
    if draft.time == TIME_ASAP:
        return None if asap_available(now) else "Мы уже не принимаем заказы «как можно скорее» — выберите время."
    if draft.time.startswith("in_"):
        return None if int(draft.time[3:]) in quick_pickup_options(now) else \
            "Это время уже недоступно — выберите другое."
    at = parse_time(draft.time, now)
    if not hours.is_valid_order_time(at, lead_minutes(draft.method), now):
        return "Выбранное время уже недоступно — выберите другое."
    return None


# ---------------------------------------------------------------------------
# Прочие поля
# ---------------------------------------------------------------------------

def clean_address(raw: str | None) -> str | None:
    text = " ".join((raw or "").split())
    if not (ADDRESS_MIN <= len(text) <= ADDRESS_MAX):
        return None
    return text


def clean_comment(raw: str | None) -> str | None:
    text = (raw or "").strip()
    return text[:COMMENT_MAX] if text else None


METHOD_TITLES = {
    OrderMethod.DELIVERY: "🛵 Доставка",
    OrderMethod.PICKUP: "🏃 Самовывоз",
    OrderMethod.TABLE: "🍽 За столиком",
}

PAYMENT_TITLES = {
    PaymentMethod.ONLINE: "💳 Онлайн-оплата",
    PaymentMethod.CASH: "💵 Наличными при получении",
    PaymentMethod.CARD: "💳 Картой при получении",
    PaymentMethod.ON_SITE: "🧾 Оплата на месте",
}
