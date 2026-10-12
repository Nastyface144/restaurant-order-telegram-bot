"""Часы работы заведения и сетка времени для заказов «ко времени» и броней."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import config
from utils.timeutil import now_local


def _intervals_starting_on(day: date) -> list[tuple[datetime, datetime]]:
    """Интервалы работы, которые начинаются в этот день (закрытие может быть на следующий)."""
    hours = config.WORKING_HOURS.get(day.weekday())
    if not hours:
        return []
    open_t, close_t = hours
    start = datetime.combine(day, open_t, tzinfo=config.TIMEZONE)
    end = datetime.combine(day, close_t, tzinfo=config.TIMEZONE)
    if close_t <= open_t:  # работает после полуночи
        end += timedelta(days=1)
    return [(start, end)]


def intervals_between(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Все интервалы работы, пересекающиеся с [start, end)."""
    result = []
    day = start.date() - timedelta(days=1)  # вчерашний интервал мог перейти через полночь
    while day <= end.date():
        for i_start, i_end in _intervals_starting_on(day):
            if i_end > start and i_start < end:
                result.append((i_start, i_end))
        day += timedelta(days=1)
    return result


def current_interval(at: datetime | None = None) -> tuple[datetime, datetime] | None:
    at = at or now_local()
    for i_start, i_end in intervals_between(at, at + timedelta(seconds=1)):
        if i_start <= at < i_end:
            return i_start, i_end
    return None


def is_open(at: datetime | None = None) -> bool:
    return current_interval(at) is not None


def accepts_orders_now(at: datetime | None = None) -> bool:
    """Открыто и до закрытия больше, чем LAST_ORDER_BEFORE_CLOSE_MINUTES."""
    at = at or now_local()
    interval = current_interval(at)
    if interval is None:
        return False
    return at < interval[1] - timedelta(minutes=config.LAST_ORDER_BEFORE_CLOSE_MINUTES)


def next_opening(at: datetime | None = None, days_ahead: int = 14) -> datetime | None:
    """Ближайшее открытие строго после `at` (если сейчас закрыто — когда откроемся)."""
    at = at or now_local()
    for i_start, _ in intervals_between(at, at + timedelta(days=days_ahead)):
        if i_start > at:
            return i_start
    return None


def ceil_to_step(dt: datetime, step_minutes: int) -> datetime:
    dt = dt.replace(second=0, microsecond=0) + (timedelta(minutes=1) if dt.second or dt.microsecond else timedelta())
    minutes = dt.hour * 60 + dt.minute
    rounded = -(-minutes // step_minutes) * step_minutes
    return dt.replace(hour=0, minute=0) + timedelta(minutes=rounded)


def time_slots(
    *,
    lead_minutes: int,
    step_minutes: int | None = None,
    last_before_close_minutes: int | None = None,
    days: int = 2,
    limit: int = 24,
    now: datetime | None = None,
) -> list[datetime]:
    """Сетка времени для заказа «ко времени».

    Слот не раньше чем через lead_minutes от текущего момента и не раньше чем через
    lead_minutes после открытия (кухне нужно время приготовить), и не позже чем за
    last_before_close_minutes до закрытия.
    """
    now = now or now_local()
    step_minutes = step_minutes or config.TIME_SLOT_STEP_MINUTES
    if last_before_close_minutes is None:
        last_before_close_minutes = config.LAST_ORDER_BEFORE_CLOSE_MINUTES
    horizon = datetime.combine(now.date() + timedelta(days=days), time(), tzinfo=config.TIMEZONE)
    slots: list[datetime] = []
    for i_start, i_end in intervals_between(now, horizon):
        earliest = max(now, i_start) + timedelta(minutes=lead_minutes)
        latest = i_end - timedelta(minutes=last_before_close_minutes)
        slot = ceil_to_step(earliest, step_minutes)
        while slot <= latest and slot < horizon:
            slots.append(slot)
            if len(slots) >= limit:
                return slots
            slot += timedelta(minutes=step_minutes)
    return slots


def slots_for_day(
    day: date,
    *,
    lead_minutes: int,
    last_before_close_minutes: int,
    step_minutes: int | None = None,
    now: datetime | None = None,
) -> list[datetime]:
    """Слоты на конкретную дату (для брони)."""
    now = now or now_local()
    step_minutes = step_minutes or config.TIME_SLOT_STEP_MINUTES
    day_start = datetime.combine(day, time(), tzinfo=config.TIMEZONE)
    day_end = day_start + timedelta(days=1)
    result = []
    for i_start, i_end in intervals_between(day_start, day_end):
        earliest = max(i_start, now + timedelta(minutes=lead_minutes), day_start)
        latest = min(i_end - timedelta(minutes=last_before_close_minutes), day_end - timedelta(minutes=1))
        slot = ceil_to_step(earliest, step_minutes)
        while slot <= latest:
            result.append(slot)
            slot += timedelta(minutes=step_minutes)
    return result


def is_valid_order_time(at: datetime, lead_minutes: int, now: datetime | None = None) -> bool:
    """Проверка выбранного времени перед созданием заказа (пока клиент думал, оно могло «уйти»)."""
    now = now or now_local()
    if at < now + timedelta(minutes=lead_minutes) - timedelta(minutes=5):  # небольшой запас
        return False
    interval = current_interval(at)
    if interval is None:
        return False
    return at <= interval[1] - timedelta(minutes=config.LAST_ORDER_BEFORE_CLOSE_MINUTES)


def format_hours() -> str:
    """Часы работы для «Контактов»: одинаковые дни склеиваются (пн–чт 10:00–23:00)."""
    names = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
    groups: list[tuple[int, int, tuple[time, time] | None]] = []
    for wd in range(7):
        hours = config.WORKING_HOURS.get(wd)
        if groups and groups[-1][2] == hours:
            groups[-1] = (groups[-1][0], wd, hours)
        else:
            groups.append((wd, wd, hours))
    lines = []
    for first, last, hours in groups:
        days = names[first] if first == last else f"{names[first]}–{names[last]}"
        value = f"{hours[0]:%H:%M}–{hours[1]:%H:%M}" if hours else "выходной"
        lines.append(f"{days}: {value}")
    return "\n".join(lines)
