from datetime import datetime, time

import pytest

import config
from orders import hours

TZ = config.TIMEZONE


def at(day: int, hh: int, mm: int = 0) -> datetime:
    # 2026-10-12 — понедельник
    return datetime(2026, 10, 12 + day, hh, mm, tzinfo=TZ)


@pytest.fixture
def week(monkeypatch):
    monkeypatch.setattr(config, "WORKING_HOURS", {
        0: (time(10), time(22)),
        1: (time(10), time(22)),
        2: None,                     # среда — выходной
        3: (time(18), time(2)),      # четверг до 02:00 пятницы
        4: (time(10), time(22)),
        5: (time(10), time(22)),
        6: (time(10), time(22)),
    })
    monkeypatch.setattr(config, "LAST_ORDER_BEFORE_CLOSE_MINUTES", 15)


def test_is_open(week):
    assert not hours.is_open(at(0, 9, 59))
    assert hours.is_open(at(0, 10))
    assert not hours.is_open(at(0, 22))
    assert not hours.is_open(at(2, 12))          # выходной
    assert hours.is_open(at(3, 23, 30))          # четверг вечером
    assert hours.is_open(at(4, 1, 30))           # пятница ночью — ещё четверговая смена
    assert not hours.is_open(at(4, 2, 0))


def test_accepts_orders_before_close(week):
    assert hours.accepts_orders_now(at(0, 21, 44))
    assert not hours.accepts_orders_now(at(0, 21, 46))


def test_next_opening(week):
    assert hours.next_opening(at(0, 7)) == at(0, 10)
    assert hours.next_opening(at(1, 23)) == at(3, 18)  # через выходной


def test_time_slots_when_open(week):
    slots = hours.time_slots(lead_minutes=60, step_minutes=30, now=at(0, 20, 10))
    # 21:10 → округляем до 21:30, последний слот 21:45 не попадает в сетку
    assert slots[0] == at(0, 21, 30)
    assert at(1, 11) in slots                # завтра: открытие 10:00 + 60 минут
    assert at(1, 10, 30) not in slots


def test_time_slots_when_closed_offers_opening(week):
    slots = hours.time_slots(lead_minutes=15, step_minutes=30, now=at(0, 6))
    assert slots[0] == at(0, 10, 30)


def test_time_slots_overnight(week):
    slots = hours.time_slots(lead_minutes=30, step_minutes=30, now=at(3, 23, 50), days=2)
    assert slots[0] == at(4, 0, 30)
    assert at(4, 1, 30) in slots
    assert at(4, 2, 0) not in slots


def test_slots_for_day(week):
    slots = hours.slots_for_day(at(1, 0).date(), lead_minutes=60, last_before_close_minutes=90, now=at(0, 12))
    assert slots[0] == at(1, 10) and slots[-1] == at(1, 20, 30)
    assert hours.slots_for_day(at(2, 0).date(), lead_minutes=60, last_before_close_minutes=90, now=at(0, 12)) == []


def test_is_valid_order_time(week):
    now = at(0, 12)
    assert hours.is_valid_order_time(at(0, 13), 60, now=now)
    assert not hours.is_valid_order_time(at(0, 12, 20), 60, now=now)
    assert not hours.is_valid_order_time(at(0, 21, 50), 60, now=now)
    assert not hours.is_valid_order_time(at(2, 12), 60, now=now)


def test_ceil_to_step():
    assert hours.ceil_to_step(datetime(2026, 1, 1, 10, 0, tzinfo=TZ), 30) == datetime(2026, 1, 1, 10, 0, tzinfo=TZ)
    assert hours.ceil_to_step(datetime(2026, 1, 1, 10, 0, 5, tzinfo=TZ), 30) == datetime(2026, 1, 1, 10, 30, tzinfo=TZ)
    assert hours.ceil_to_step(datetime(2026, 1, 1, 23, 50, tzinfo=TZ), 30) == datetime(2026, 1, 2, 0, 0, tzinfo=TZ)


def test_format_hours(week):
    assert hours.format_hours().splitlines() == [
        "пн–вт: 10:00–22:00", "ср: выходной", "чт: 18:00–02:00", "пт–вс: 10:00–22:00",
    ]
