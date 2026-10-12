from datetime import timedelta

import pytest
from aiogram.methods import SendMessage

import config
from database import bookings, orders
from database.models import BookingStatus, OrderStatus
from orders import scheduler
from tests.test_checkout import STAFF, USER, add_pizza, open_checkout
from tests.test_payment import checkout_online
from utils.timeutil import now_local

ADMIN = 8008


@pytest.fixture(autouse=True)
async def running_scheduler(harness, monkeypatch):
    monkeypatch.setattr(config, "STAFF_CHAT_ID", STAFF)
    monkeypatch.setattr(config, "ADMIN_IDS", (ADMIN,))
    await scheduler.start(harness.bot)
    yield
    scheduler.shutdown()


def job_ids() -> set[str]:
    return {job.id for job in scheduler._scheduler.get_jobs()}


async def place_scheduled_pickup(h):
    await add_pizza()
    await open_checkout(h)
    await h.click(USER, "Самовывоз")
    await h.click(USER, "К конкретному времени")
    slots = [b for b in h.buttons(USER) if ":" in b and not b.startswith("📅")]
    await h.click(USER, slots[-1], exact=True)  # самое позднее — чтобы напоминание было в будущем
    await h.send(USER, "+79990000000")
    await h.click(USER, "Без комментария")
    await h.click(USER, "Наличными")
    await h.click(USER, "Подтвердить")
    return await orders.get_order(1)


async def test_base_jobs(harness, always_open):
    assert {"cancel-unpaid", "daily-report"} <= job_ids()


async def test_scheduled_order_reminder(harness, always_open):
    order = await place_scheduled_pickup(harness)
    assert order.scheduled_at is not None
    assert f"order-reminder-{order.id}" in job_ids()

    await scheduler.remind_staff_about_order(order.id)
    reminder = harness.session.calls(SendMessage)[-1]
    assert reminder.chat_id == STAFF and "пора начинать готовить" in reminder.text
    assert reminder.reply_to_message_id == order.staff_message_id

    # отклонённому заказу напоминание не нужно
    await orders.update_status(order.id, OrderStatus.REJECTED, expected=[OrderStatus.NEW])
    before = len(harness.session.calls(SendMessage))
    await scheduler.remind_staff_about_order(order.id)
    assert len(harness.session.calls(SendMessage)) == before


async def test_jobs_restored_after_restart(harness, always_open):
    order = await place_scheduled_pickup(harness)
    scheduler.shutdown()
    await scheduler.start(harness.bot)
    assert f"order-reminder-{order.id}" in job_ids()


async def test_cancel_unpaid_orders(harness, always_open, monkeypatch):
    monkeypatch.setattr(config, "PAYMENT_TOKEN", "1:TEST:1")
    monkeypatch.setattr(config, "FEATURES", config.Features(online_payment=True))
    await checkout_online(harness)
    assert await scheduler.cancel_unpaid_orders() == 0  # ещё рано

    monkeypatch.setattr(config, "UNPAID_ORDER_TIMEOUT_MINUTES", -1)
    assert await scheduler.cancel_unpaid_orders() == 1
    assert (await orders.get_order(1)).status == OrderStatus.CANCELLED
    assert "оплата не поступила" in harness.session.calls(SendMessage)[-1].text


async def test_booking_reminder(harness):
    starts = now_local().replace(second=0, microsecond=0) + timedelta(days=1)
    booking_id = await bookings.create_booking(user_id=USER, starts_at=starts, guests=2, name="Анна", phone="+7")
    await bookings.update_status(booking_id, BookingStatus.CONFIRMED, expected=BookingStatus.PENDING)
    scheduler.schedule_booking_reminder(await bookings.get_booking(booking_id))
    assert f"booking-reminder-{booking_id}" in job_ids()

    await scheduler.remind_guest_about_booking(booking_id)
    reminder = harness.session.calls(SendMessage)[-1]
    assert reminder.chat_id == USER and f"{starts:%H:%M}" in reminder.text and "2 гостя" in reminder.text


async def test_daily_report(harness, always_open):
    await scheduler.send_daily_report()
    report = harness.session.calls(SendMessage)[-1]
    assert report.chat_id == ADMIN and "Итоги дня" in report.text
