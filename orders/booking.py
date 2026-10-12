"""Бронь столика: шаги, доступные даты и время, тексты."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timedelta

import config
from database.models import Booking, BookingStatus
from utils.format import esc, format_phone, plural
from utils.timeutil import human_date, human_datetime, now_local

from . import hours

STEPS = ("date", "time", "guests", "name", "phone", "confirm")
NAME_MIN, NAME_MAX = 2, 50

STATUS_LABELS = {
    BookingStatus.PENDING: "⏳ Ждёт подтверждения",
    BookingStatus.CONFIRMED: "✅ Подтверждена",
    BookingStatus.REJECTED: "❌ Отклонена",
    BookingStatus.CANCELLED: "🚫 Отменена",
}


@dataclass
class BookingDraft:
    day: str | None = None    # YYYYMMDD
    time: str | None = None   # HHMM
    guests: int | None = None
    name: str | None = None
    phone: str | None = None
    step: str = "date"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> BookingDraft:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})

    @property
    def date(self) -> date | None:
        return datetime.strptime(self.day, "%Y%m%d").date() if self.day else None

    @property
    def starts_at(self) -> datetime | None:
        if not (self.day and self.time):
            return None
        return datetime.strptime(self.day + self.time, "%Y%m%d%H%M").replace(tzinfo=config.TIMEZONE)

    def is_filled(self, step: str) -> bool:
        return {
            "date": bool(self.day),
            "time": bool(self.time),
            "guests": bool(self.guests),
            "name": bool(self.name),
            "phone": bool(self.phone),
        }.get(step, False)

    def advance(self) -> str:
        start = STEPS.index(self.step) + 1 if self.step in STEPS else 0
        for step in STEPS[start:]:
            if not self.is_filled(step):
                return step
        return "confirm"

    def prev(self) -> str | None:
        index = STEPS.index(self.step) if self.step in STEPS else 0
        return STEPS[index - 1] if index > 0 else None


def day_slots(day: date, now: datetime | None = None) -> list[datetime]:
    return hours.slots_for_day(
        day,
        lead_minutes=config.BOOKING_MIN_LEAD_MINUTES,
        last_before_close_minutes=config.BOOKING_LAST_BEFORE_CLOSE_MINUTES,
        now=now,
    )


def available_days(now: datetime | None = None) -> list[date]:
    now = now or now_local()
    days = [now.date() + timedelta(days=i) for i in range(config.BOOKING_DAYS_AHEAD)]
    return [d for d in days if day_slots(d, now)]


def is_slot_available(starts_at: datetime, now: datetime | None = None) -> bool:
    return starts_at in day_slots(starts_at.date(), now)


def guests_text(n: int) -> str:
    return f"{n} {plural(n, 'гость', 'гостя', 'гостей')}"


def clean_name(raw: str | None) -> str | None:
    text = " ".join((raw or "").split())
    return text if NAME_MIN <= len(text) <= NAME_MAX else None


def summary(draft: BookingDraft) -> str:
    return "\n".join([
        f"🗓 {human_datetime(draft.starts_at).capitalize()}",
        f"👥 {guests_text(draft.guests)}",
        f"👤 {esc(draft.name)}",
        f"📞 {format_phone(draft.phone)}",
    ])


def admin_card(booking: Booking, username: str | None = None) -> str:
    who = f'<a href="tg://user?id={booking.user_id}">{esc(booking.name)}</a>'
    if username:
        who += f" (@{esc(username)})"
    lines = [
        f"📅 <b>Бронь №{booking.id}</b>",
        f"🗓 {human_date(booking.starts_at.date()).capitalize()} в {booking.starts_at:%H:%M}"
        f" ({booking.starts_at:%d.%m})",
        f"👥 {guests_text(booking.guests)}",
        f"👤 {who}",
        f"📞 {format_phone(booking.phone)}",
        "",
        f"Статус: <b>{STATUS_LABELS[booking.status]}</b>",
    ]
    if booking.decided_by:
        lines.append(f"<i>{esc(booking.decided_by)}</i>")
    return "\n".join(lines)


def client_line(booking: Booking) -> str:
    return (f"• {human_datetime(booking.starts_at).capitalize()}, {guests_text(booking.guests)} — "
            f"{STATUS_LABELS[booking.status]}")


def client_notification(booking: Booking) -> str | None:
    when = human_datetime(booking.starts_at)
    if booking.status == BookingStatus.CONFIRMED:
        return (f"✅ Бронь подтверждена! Ждём вас {when}, {guests_text(booking.guests)}.\n"
                f"📍 {esc(config.VENUE_ADDRESS)}")
    if booking.status == BookingStatus.REJECTED:
        return (f"😔 К сожалению, на {when} свободных столиков нет. "
                f"Попробуйте выбрать другое время или позвоните нам: {esc(config.VENUE_PHONE)}")
    return None
