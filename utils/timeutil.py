"""Работа со временем.

В базе всё хранится в UTC строкой «YYYY-MM-DD HH:MM:SS», а пользователю
показывается в часовом поясе заведения (config.TIMEZONE).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import config

DB_FORMAT = "%Y-%m-%d %H:%M:%S"

WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def now_local() -> datetime:
    return datetime.now(config.TIMEZONE)


def to_db(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=config.TIMEZONE)
    return dt.astimezone(timezone.utc).strftime(DB_FORMAT)


def from_db(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, DB_FORMAT).replace(tzinfo=timezone.utc).astimezone(config.TIMEZONE)


def now_db() -> str:
    return to_db(now_local())


def local_day_bounds_db(day: date) -> tuple[str, str]:
    """Начало и конец локальных суток в формате БД (полуинтервал [start, end))."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=config.TIMEZONE)
    end = datetime.fromordinal(day.toordinal() + 1).replace(tzinfo=config.TIMEZONE)
    return to_db(start), to_db(end)


def human_date(day: date, today: date | None = None) -> str:
    """«сегодня», «завтра» или «пт, 14 октября»."""
    today = today or now_local().date()
    delta = (day - today).days
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    return f"{WEEKDAYS_SHORT[day.weekday()]}, {day.day} {MONTHS_GENITIVE[day.month - 1]}"


def human_datetime(dt: datetime, today: date | None = None) -> str:
    """«сегодня в 19:30»."""
    return f"{human_date(dt.date(), today)} в {dt:%H:%M}"
