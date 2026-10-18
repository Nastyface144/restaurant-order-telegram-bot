"""Настройки бота.

Секреты (токены, ID) читаются из .env, всё остальное — настройки заведения —
задаётся прямо в этом файле. Чтобы адаптировать бота под другое заведение,
обычно достаточно поменять этот файл и демо-меню в database/demo_data.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    """Ошибка в настройках: бот не может запуститься."""


def _int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Переменная окружения {name} должна быть числом, получено: {raw!r}") from exc


def _int_list_env(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "")
    result = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError as exc:
            raise ConfigError(f"В {name} должны быть числовые ID через запятую, получено: {part!r}") from exc
    return tuple(result)


# ---------------------------------------------------------------------------
# Секреты из .env
# ---------------------------------------------------------------------------

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
# ID рабочего чата персонала (группа, куда приходят заказы). Обычно отрицательный.
STAFF_CHAT_ID: int = _int_env("STAFF_CHAT_ID")
# ID администраторов: можно указать несколько через запятую.
ADMIN_IDS: tuple[int, ...] = _int_list_env("ADMIN_ID")
# Платёжный токен ЮKassa из @BotFather → Payments. Пусто — онлайн-оплата скрыта.
PAYMENT_TOKEN: str = os.getenv("PAYMENT_TOKEN", "").strip()

DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data/bot.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


# ---------------------------------------------------------------------------
# Заведение
# ---------------------------------------------------------------------------

VENUE_NAME = "Пицца у дома"
VENUE_TAGLINE = "Горячая пицца из печи — к вам домой, с собой или за столиком"
VENUE_ADDRESS = "г. Москва, ул. Садовая, 12"
VENUE_PHONE = "+7 (999) 123-45-67"
# Ссылка на карту (кнопка в «Контактах»). Пусто — кнопки не будет.
VENUE_MAP_URL = "https://yandex.ru/maps/?text=Москва%2C%20Садовая%2012"

TIMEZONE = ZoneInfo("Europe/Moscow")
CURRENCY = "RUB"
CURRENCY_SIGN = "₽"

# Часы работы по дням недели: 0 — понедельник … 6 — воскресенье.
# None — выходной. Если закрытие раньше открытия (например, 10:00–02:00),
# считается, что заведение работает после полуночи.
WORKING_HOURS: dict[int, tuple[time, time] | None] = {
    0: (time(10, 0), time(23, 0)),
    1: (time(10, 0), time(23, 0)),
    2: (time(10, 0), time(23, 0)),
    3: (time(10, 0), time(23, 0)),
    4: (time(10, 0), time(23, 59)),
    5: (time(11, 0), time(23, 59)),
    6: (time(11, 0), time(22, 0)),
}


# ---------------------------------------------------------------------------
# Режимы заказа — каждый включается и выключается флагом
# ---------------------------------------------------------------------------

ENABLE_DELIVERY = True   # доставка курьером
ENABLE_PICKUP = True     # самовывоз
ENABLE_TABLE = True      # заказ за столиком по QR-коду (/start table_N)
ENABLE_BOOKING = True    # бронь столика

# Способы оплаты. Онлайн-оплата дополнительно требует PAYMENT_TOKEN в .env.
ENABLE_ONLINE_PAYMENT = True
ENABLE_CASH_PAYMENT = True
ENABLE_CARD_ON_RECEIPT = True


# ---------------------------------------------------------------------------
# Доставка
# ---------------------------------------------------------------------------

DELIVERY_PRICE = 199         # стоимость доставки, ₽ (0 — всегда бесплатно)
DELIVERY_MIN_ORDER = 700     # минимальная сумма заказа на доставку, ₽ (0 — без минимума)
DELIVERY_FREE_FROM = 2000    # бесплатная доставка от этой суммы, ₽ (0 — никогда)
DELIVERY_ETA_MINUTES = 45    # сколько обычно едет заказ «как можно скорее»

# Сколько минут минимум нужно на заказ «ко времени» от текущего момента.
DELIVERY_LEAD_MINUTES = 60
PICKUP_LEAD_MINUTES = 15
# Варианты быстрого самовывоза «через N минут».
PICKUP_QUICK_OPTIONS: tuple[int, ...] = (15, 30, 60)
# Шаг сетки времени для заказа «ко времени» и брони, минут.
TIME_SLOT_STEP_MINUTES = 30
# За сколько минут до закрытия перестаём принимать заказы.
LAST_ORDER_BEFORE_CLOSE_MINUTES = 15


# ---------------------------------------------------------------------------
# Столики и бронь
# ---------------------------------------------------------------------------

TABLES_COUNT = 15              # столы с номерами 1…N (для QR-кодов)
TABLE_SESSION_HOURS = 4        # сколько часов бот «помнит», что гость за столом
BOOKING_DAYS_AHEAD = 7         # на сколько дней вперёд можно бронировать
BOOKING_MAX_GUESTS = 8         # больше — «позвоните нам»
BOOKING_LAST_BEFORE_CLOSE_MINUTES = 90  # последняя бронь за N минут до закрытия
BOOKING_MIN_LEAD_MINUTES = 60  # бронь не раньше чем через N минут
BOOKING_REMINDER_MINUTES = 120  # напоминание гостю за N минут до брони


# ---------------------------------------------------------------------------
# Персонал и планировщик
# ---------------------------------------------------------------------------

# Причины отклонения заказа (кнопки в рабочем чате).
REJECT_REASONS: tuple[str, ...] = (
    "Нет нужных продуктов",
    "Не доставляем по этому адресу",
    "Кухня перегружена",
    "Скоро закрываемся",
    "Не дозвонились до клиента",
)

# За сколько минут до времени заказа напомнить персоналу о заказе «ко времени».
SCHEDULED_ORDER_REMINDER_MINUTES = 45
# Через сколько минут отменять заказ, который так и не оплатили онлайн.
UNPAID_ORDER_TIMEOUT_MINUTES = 30
# Ежедневный отчёт администратору (локальное время). None — не отправлять.
DAILY_REPORT_TIME: time | None = time(23, 59)


# ---------------------------------------------------------------------------
# Производные настройки — обычно менять не нужно
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Features:
    delivery: bool = ENABLE_DELIVERY
    pickup: bool = ENABLE_PICKUP
    table: bool = ENABLE_TABLE
    booking: bool = ENABLE_BOOKING
    online_payment: bool = field(default_factory=lambda: ENABLE_ONLINE_PAYMENT and bool(PAYMENT_TOKEN))
    cash_payment: bool = ENABLE_CASH_PAYMENT
    card_on_receipt: bool = ENABLE_CARD_ON_RECEIPT

    @property
    def ordering(self) -> bool:
        """Можно ли вообще оформлять заказы."""
        return self.delivery or self.pickup or self.table

    @property
    def remote_ordering(self) -> bool:
        """Есть ли способы заказа не из-за стола."""
        return self.delivery or self.pickup


FEATURES = Features()


def validate() -> list[str]:
    """Проверяет настройки при запуске. Возвращает список предупреждений,
    а на критичных ошибках бросает ConfigError."""
    if not BOT_TOKEN:
        raise ConfigError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и заполните его.")

    warnings: list[str] = []
    if not STAFF_CHAT_ID:
        warnings.append("STAFF_CHAT_ID не задан — заказы не будут приходить персоналу.")
    if not ADMIN_IDS:
        warnings.append("ADMIN_ID не задан — /admin и подтверждение броней недоступны.")
    if ENABLE_ONLINE_PAYMENT and not PAYMENT_TOKEN:
        warnings.append("PAYMENT_TOKEN не задан — онлайн-оплата отключена.")
    if min(DELIVERY_PRICE, DELIVERY_MIN_ORDER, DELIVERY_FREE_FROM, DELIVERY_ETA_MINUTES) < 0:
        raise ConfigError("Настройки доставки (DELIVERY_*) не могут быть отрицательными.")
    if FEATURES.ordering and not (FEATURES.online_payment or FEATURES.cash_payment or FEATURES.card_on_receipt):
        raise ConfigError("Не включён ни один способ оплаты.")
    if not any(WORKING_HOURS.values()):
        raise ConfigError("В WORKING_HOURS нет ни одного рабочего дня.")
    return warnings
