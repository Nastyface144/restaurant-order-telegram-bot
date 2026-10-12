"""Сводка за день для админ-панели и ежедневного отчёта."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from database import bookings as bookings_db
from database import menu, users
from database import orders as orders_db
from database.models import Booking, BookingStatus, Order, OrderStatus
from orders.booking import guests_text
from orders.statuses import ACTIVE_STATUSES
from utils.format import money, plural
from utils.timeutil import human_date


@dataclass(frozen=True)
class DayStats:
    day: date
    orders: list[Order]
    bookings: list[Booking]
    stopped_items: int
    users_total: int
    users_active: int

    @property
    def by_status(self) -> Counter:
        return Counter(o.status for o in self.orders)

    @property
    def completed(self) -> list[Order]:
        return [o for o in self.orders if o.status == OrderStatus.COMPLETED]

    @property
    def in_progress(self) -> list[Order]:
        return [o for o in self.orders if o.status in ACTIVE_STATUSES]

    @property
    def revenue(self) -> int:
        """Выручка — выполненные заказы."""
        return sum(o.total for o in self.completed)

    @property
    def expected_revenue(self) -> int:
        """Сумма заказов, которые ещё в работе."""
        return sum(o.total for o in self.in_progress)

    @property
    def average_check(self) -> int:
        return round(self.revenue / len(self.completed)) if self.completed else 0

    @property
    def pending_bookings(self) -> int:
        return sum(b.status == BookingStatus.PENDING for b in self.bookings)

    @property
    def guests_expected(self) -> int:
        return sum(b.guests for b in self.bookings if b.status == BookingStatus.CONFIRMED)


async def collect(day: date) -> DayStats:
    total, active = await users.count_users()
    return DayStats(
        day=day,
        orders=await orders_db.get_orders_for_day(day),
        bookings=await bookings_db.get_bookings_for_day(day),
        stopped_items=await menu.count_stopped(),
        users_total=total,
        users_active=active,
    )


def format_summary(s: DayStats, title: str) -> str:
    by_status = s.by_status
    lines = [f"{title} · {human_date(s.day)}, {s.day:%d.%m}", ""]
    lines.append(f"🧾 Заказов: <b>{len(s.orders)}</b>")
    if s.orders:
        lines.append(
            f"    в работе {len(s.in_progress)} · выполнено {len(s.completed)} · "
            f"отклонено {by_status[OrderStatus.REJECTED]}"
        )
    lines.append(f"💰 Выручка: <b>{money(s.revenue)}</b>")
    if s.completed:
        lines.append(f"    средний чек {money(s.average_check)}")
    if s.expected_revenue:
        lines.append(f"    ещё в работе на {money(s.expected_revenue)}")
    lines.append(f"📅 Броней: <b>{len(s.bookings)}</b>"
                 + (f" · ждут подтверждения {s.pending_bookings}" if s.pending_bookings else ""))
    if s.guests_expected:
        lines.append(f"    ожидаем {guests_text(s.guests_expected)}")
    lines.append(f"🚫 В стоп-листе: {s.stopped_items} {plural(s.stopped_items, 'блюдо', 'блюда', 'блюд')}")
    lines.append(f"👥 Клиентов в боте: {s.users_active}")
    return "\n".join(lines)
