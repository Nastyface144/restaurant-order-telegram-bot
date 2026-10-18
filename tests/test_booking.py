from datetime import time

import pytest
from aiogram.methods import AnswerCallbackQuery, SendMessage

import config
from database import bookings, users
from database.models import BookingStatus

USER = 6006
ADMIN = 7007


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", (ADMIN,))
    monkeypatch.setattr(config, "WORKING_HOURS", {d: (time(10), time(23)) for d in range(7)})


async def book(h, guests="4", name_typed=None):
    await h.send(USER, "/start")
    await h.click(USER, "Забронировать")
    await h.click(USER, "Завтра")
    await h.click(USER, "19:00", exact=True)
    await h.click(USER, guests, exact=True)
    if name_typed:
        await h.send(USER, name_typed)
    else:
        await h.click(USER, "👤")
    await h.send(USER, "+7 999 111-22-33")


async def test_full_booking_flow(harness):
    await book(harness, name_typed="Анна")
    text = harness.screen_text(USER)
    assert "Завтра в 19:00" in text and "4 гостя" in text and "Анна" in text
    await harness.click(USER, "Отправить заявку")
    assert "Заявка отправлена" in harness.screen_text(USER)
    assert len(harness.session.chat_messages(USER)) == 1

    booking = await bookings.get_booking(1)
    assert booking.status == BookingStatus.PENDING and booking.guests == 4
    assert (booking.starts_at.hour, booking.starts_at.minute) == (19, 0)
    card = harness.session.last_message(ADMIN)
    assert "Бронь №1" in card["text"] and "Ждёт подтверждения" in card["text"]
    assert booking.admin_messages == ((ADMIN, card["message_id"]),)

    await harness.click(ADMIN, "Подтвердить")
    assert (await bookings.get_booking(1)).status == BookingStatus.CONFIRMED
    assert "✅ Подтверждена" in harness.session.last_message(ADMIN)["text"]
    assert harness.buttons(ADMIN) == []
    note = [m.text for m in harness.session.calls(SendMessage) if m.chat_id == USER][-1]
    assert "Бронь подтверждена" in note

    # повторное решение невозможно
    await harness.click(ADMIN, "Нет мест", message=card)
    assert "уже принято решение" in harness.session.calls(AnswerCallbackQuery)[-1].text

    # бронь видна в разделе
    await harness.send(USER, "/start")
    await harness.click(USER, "Забронировать")
    assert "Ваши брони" in harness.screen_text(USER) and "Подтверждена" in harness.screen_text(USER)


async def test_reject_booking(harness):
    await book(harness, guests="2")
    await harness.click(USER, "Отправить заявку")
    await harness.click(ADMIN, "Нет мест")
    assert (await bookings.get_booking(1)).status == BookingStatus.REJECTED
    note = [m.text for m in harness.session.calls(SendMessage) if m.chat_id == USER][-1]
    assert "свободных столиков нет" in note


async def test_back_navigation_and_validation(harness):
    await harness.send(USER, "/start")
    await harness.click(USER, "Забронировать")
    await harness.click(USER, "Завтра")
    await harness.click(USER, "Назад")
    assert "Выберите день" in harness.screen_text(USER)
    await harness.click(USER, "Завтра")
    await harness.click(USER, "20:00", exact=True)
    await harness.click(USER, "3", exact=True)
    await harness.send(USER, "Я")  # слишком короткое имя
    assert "Имя — от 2" in harness.screen_text(USER)
    await harness.send(USER, "Пётр")
    await harness.send(USER, "12345")
    assert "Не похоже на номер" in harness.screen_text(USER)
    await harness.send(USER, "+79001112233")
    assert "Проверьте заявку" in harness.screen_text(USER)
    await harness.click(USER, "Назад")
    await harness.click(USER, "Назад")
    assert "На чьё имя" in harness.screen_text(USER)
    await harness.send(USER, "Пётр Иванов")
    assert "Проверьте заявку" in harness.screen_text(USER)  # остальное уже заполнено
    assert (await users.get_user(USER)) is not None


async def test_stranger_cannot_decide(harness):
    await book(harness)
    await harness.click(USER, "Отправить заявку")
    card = harness.session.last_message(ADMIN)
    stranger_view = {**card, "chat": {"id": 1234, "type": "private", "first_name": "x"}}
    await harness.click(1234, "Подтвердить", message=stranger_view)
    assert (await bookings.get_booking(1)).status == BookingStatus.PENDING


async def test_booking_disabled(harness, monkeypatch):
    monkeypatch.setattr(config, "FEATURES", config.Features(booking=False))
    await harness.send(USER, "/start")
    assert "📅 Забронировать" not in harness.buttons(USER)
