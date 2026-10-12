"""Фоновые задачи на APScheduler.

- отмена заказов, которые так и не оплатили онлайн;
- напоминание кухне о заказе «ко времени» — пора начинать готовить;
- напоминание гостю о подтверждённой брони;
- ежедневный отчёт администратору.

Задачи хранятся в памяти; при перезапуске бота напоминания восстанавливаются из БД.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database import bookings as bookings_db
from database import orders as orders_db
from database import users
from database.models import Booking, BookingStatus, Order, OrderStatus
from utils.format import esc
from utils.timeutil import now_local

from .booking import guests_text
from .statuses import ACTIVE_STATUSES

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_bot: Bot | None = None

UNPAID_CHECK_MINUTES = 5


def _is_running() -> bool:
    return _scheduler is not None and _scheduler.running


def _add_date_job(job_id: str, run_at: datetime, func, *args) -> None:
    if not _is_running():
        return
    if run_at <= now_local():
        return
    _scheduler.add_job(func, "date", run_date=run_at, args=args, id=job_id, replace_existing=True,
                       misfire_grace_time=300)


# ---------------------------------------------------------------------------
# Заказы «ко времени»
# ---------------------------------------------------------------------------

def schedule_order_reminder(order: Order) -> None:
    if order.scheduled_at is None or not config.STAFF_CHAT_ID:
        return
    run_at = order.scheduled_at - timedelta(minutes=config.SCHEDULED_ORDER_REMINDER_MINUTES)
    _add_date_job(f"order-reminder-{order.id}", run_at, remind_staff_about_order, order.id)


async def remind_staff_about_order(order_id: int) -> None:
    order = await orders_db.get_order(order_id)
    if order is None or order.status not in ACTIVE_STATUSES or order.scheduled_at is None:
        return
    text = (f"⏰ Заказ №{order.id} ко времени <b>{order.scheduled_at:%H:%M}</b> — "
            f"пора начинать готовить.")
    try:
        await _bot.send_message(config.STAFF_CHAT_ID, text, reply_to_message_id=order.staff_message_id,
                                allow_sending_without_reply=True)
    except TelegramAPIError:
        logger.exception("Не удалось напомнить о заказе №%s", order_id)


# ---------------------------------------------------------------------------
# Брони
# ---------------------------------------------------------------------------

def schedule_booking_reminder(booking: Booking) -> None:
    run_at = booking.starts_at - timedelta(minutes=config.BOOKING_REMINDER_MINUTES)
    _add_date_job(f"booking-reminder-{booking.id}", run_at, remind_guest_about_booking, booking.id)


async def remind_guest_about_booking(booking_id: int) -> None:
    booking = await bookings_db.get_booking(booking_id)
    if booking is None or booking.status != BookingStatus.CONFIRMED:
        return
    text = (f"⏰ Напоминаем: ждём вас сегодня в <b>{booking.starts_at:%H:%M}</b>, "
            f"{guests_text(booking.guests)}.\n📍 {esc(config.VENUE_ADDRESS)}\n\n"
            f"Если планы изменились — позвоните нам: {esc(config.VENUE_PHONE)}")
    try:
        await _bot.send_message(booking.user_id, text)
    except TelegramForbiddenError:
        await users.mark_blocked(booking.user_id)
    except TelegramAPIError:
        logger.exception("Не удалось напомнить о брони №%s", booking_id)


# ---------------------------------------------------------------------------
# Неоплаченные заказы
# ---------------------------------------------------------------------------

async def cancel_unpaid_orders() -> int:
    """Отменяет онлайн-заказы, не оплаченные за UNPAID_ORDER_TIMEOUT_MINUTES. Корзина у клиента остаётся."""
    deadline = now_local() - timedelta(minutes=config.UNPAID_ORDER_TIMEOUT_MINUTES)
    cancelled = 0
    for order_id in await orders_db.get_stale_unpaid(deadline):
        if not await orders_db.update_status(order_id, OrderStatus.CANCELLED,
                                             expected=[OrderStatus.PENDING_PAYMENT], changed_by="автоотмена"):
            continue
        cancelled += 1
        order = await orders_db.get_order(order_id)
        logger.info("Заказ №%s отменён: не оплачен вовремя", order_id)
        if _bot is None:
            continue
        try:
            await _bot.send_message(
                order.user_id,
                f"⌛ Заказ №{order_id} отменён — оплата не поступила. Корзина сохранена, "
                f"оформить заказ можно заново в любой момент.",
            )
        except TelegramAPIError:
            pass
    return cancelled


# ---------------------------------------------------------------------------
# Ежедневный отчёт
# ---------------------------------------------------------------------------

async def send_daily_report() -> None:
    from admin.stats import collect, format_summary

    if not config.ADMIN_IDS:
        return
    text = format_summary(await collect(now_local().date()), "📊 <b>Итоги дня</b>")
    for admin_id in config.ADMIN_IDS:
        try:
            await _bot.send_message(admin_id, text)
        except TelegramAPIError:
            logger.warning("Не удалось отправить отчёт администратору %s", admin_id)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

async def restore_jobs() -> None:
    """После перезапуска заново ставим напоминания по данным из БД."""
    now = now_local()
    orders = await orders_db.get_upcoming_scheduled(now)
    for order in orders:
        schedule_order_reminder(order)
    bookings = await bookings_db.get_upcoming_confirmed(now)
    for booking in bookings:
        schedule_booking_reminder(booking)
    logger.info("Планировщик: восстановлено напоминаний — заказы: %d, брони: %d", len(orders), len(bookings))


async def start(bot: Bot) -> AsyncIOScheduler:
    global _scheduler, _bot
    _bot = bot
    _scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
    _scheduler.add_job(cancel_unpaid_orders, "interval", minutes=UNPAID_CHECK_MINUTES, id="cancel-unpaid",
                       next_run_time=now_local() + timedelta(seconds=30))
    if config.DAILY_REPORT_TIME is not None:
        _scheduler.add_job(send_daily_report, "cron", hour=config.DAILY_REPORT_TIME.hour,
                           minute=config.DAILY_REPORT_TIME.minute, id="daily-report")
    _scheduler.start()
    await restore_jobs()
    return _scheduler


def shutdown() -> None:
    global _scheduler
    if _is_running():
        _scheduler.shutdown(wait=False)
    _scheduler = None
