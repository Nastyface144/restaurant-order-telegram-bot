"""Бронь столика: дата → время → гости → имя → телефон → заявка; решение администратора."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
from database import bookings as bookings_db
from database import users
from database.models import Booking, BookingStatus
from keyboards import booking as kb
from keyboards.callbacks import BookAdminCb, BookCb, Nav
from keyboards.common import progress_bar
from orders import booking as bk
from orders import scheduler
from orders.booking import BookingDraft
from utils import screen
from utils.format import esc, normalize_phone
from utils.timeutil import human_date, now_local

from .start import show_main_menu

logger = logging.getLogger(__name__)

router = Router(name="booking")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

DRAFT_KEY = "booking"


class BookingForm(StatesGroup):
    buttons = State()
    name = State()
    phone = State()


INPUT_STATES = {"name": BookingForm.name, "phone": BookingForm.phone}


def booking_recipients() -> list[int]:
    """Кому уходят заявки на бронь: администраторам, а если их нет — в рабочий чат."""
    if config.ADMIN_IDS:
        return list(config.ADMIN_IDS)
    return [config.STAFF_CHAT_ID] if config.STAFF_CHAT_ID else []


# ---------------------------------------------------------------------------
# Экраны
# ---------------------------------------------------------------------------

async def render(bot: Bot, chat_id: int, user_id: int, state: FSMContext, draft: BookingDraft, *,
                 message: Message | None = None, notice: str | None = None, full_name: str | None = None) -> None:
    now = now_local()
    step = draft.step
    position = bk.STEPS.index(step) + 1 if step in bk.STEPS else 1
    head = f"<b>Бронь столика</b>\n{progress_bar(position, len(bk.STEPS))}  шаг {position} из {len(bk.STEPS)}"

    if step == "date":
        days = bk.available_days(now)
        upcoming = await bookings_db.get_user_bookings(user_id, after=now)
        upcoming = [b for b in upcoming if b.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)]
        body = "📅 <b>Выберите день</b> 👇" if days else \
            f"😔 В ближайшие дни свободного времени нет. Позвоните нам: {esc(config.VENUE_PHONE)}"
        if upcoming:
            body = ("Ваши брони:\n<blockquote>" + "\n".join(bk.client_line(b) for b in upcoming)
                    + "</blockquote>\n" + body)
        keyboard = kb.dates(days, now.date())
    elif step == "time":
        slots = bk.day_slots(draft.date, now)
        body = f"🗓 {human_date(draft.date, now.date()).capitalize()} — <b>во сколько вас ждать?</b>"
        if not slots:
            body += "\n\n😔 На этот день времени не осталось — выберите другую дату."
        keyboard = kb.times(slots)
    elif step == "guests":
        body = (f"👥 <b>Сколько будет гостей?</b>\n"
                f"<i>Больше {config.BOOKING_MAX_GUESTS}? Позвоните: {esc(config.VENUE_PHONE)}</i>")
        keyboard = kb.guests()
    elif step == "name":
        body = "👤 <b>На чьё имя бронируем?</b>\nНажмите кнопку или напишите имя сообщением"
        keyboard = kb.name(full_name)
    elif step == "phone":
        user = await users.get_user(user_id)
        body = "📞 <b>Ваш телефон</b> — позвоним, если что-то изменится\n<i>Например: +7 999 123-45-67</i>"
        keyboard = kb.phone(user.phone if user else None)
    else:
        body = ("📋 <b>Проверьте заявку</b>\n<blockquote>" + bk.summary(draft) + "</blockquote>\n"
                "Администратор подтвердит бронь — мы пришлём уведомление.")
        keyboard = kb.confirm()

    text = f"{head}\n\n{body}"
    if notice:
        text = f"⚠️ {notice}\n\n{text}"
    await state.update_data({DRAFT_KEY: draft.to_dict(), "booking_name": full_name})
    await state.set_state(INPUT_STATES.get(step, BookingForm.buttons))
    await screen.show(bot, chat_id, text, keyboard, picture=screen.banner("booking"), message=message)


async def load(state: FSMContext) -> tuple[BookingDraft | None, str | None]:
    data = await state.get_data()
    raw = data.get(DRAFT_KEY)
    return (BookingDraft.from_dict(raw) if raw else None), data.get("booking_name")


async def step_done(draft: BookingDraft, step: str, bot: Bot, state: FSMContext, *, user_id: int, chat_id: int,
                    full_name: str | None, message: Message | None = None) -> None:
    draft.step = step
    draft.step = draft.advance()
    await render(bot, chat_id, user_id, state, draft, message=message, full_name=full_name)


# ---------------------------------------------------------------------------
# Клиент
# ---------------------------------------------------------------------------

@router.callback_query(Nav.filter(F.to == "booking"))
async def on_booking(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not config.FEATURES.booking:
        await callback.answer("Бронирование сейчас недоступно", show_alert=True)
        return
    await state.clear()
    await render(bot, callback.message.chat.id, callback.from_user.id, state, BookingDraft(),
                 message=callback.message, full_name=callback.from_user.first_name)
    await callback.answer()


@router.callback_query(BookCb.filter())
async def on_booking_step(callback: CallbackQuery, callback_data: BookCb, state: FSMContext, bot: Bot) -> None:
    draft, full_name = await load(state)
    if draft is None:
        await callback.answer("Бронирование прервалось — начните заново", show_alert=True)
        draft, full_name = BookingDraft(), callback.from_user.first_name
        await render(bot, callback.message.chat.id, callback.from_user.id, state, draft,
                     message=callback.message, full_name=full_name)
        return

    nav = dict(user_id=callback.from_user.id, chat_id=callback.message.chat.id,
               full_name=full_name, message=callback.message)
    action, value = callback_data.a, callback_data.v

    if action == "back":
        previous = draft.prev()
        if previous is None:
            await state.clear()
            await show_main_menu(bot, callback.message.chat.id, callback.from_user.id, message=callback.message)
        else:
            draft.step = previous
            await render(bot, state=state, draft=draft, **nav)
        await callback.answer()
        return

    if action == "date":
        if len(value) != 8 or not value.isdigit():
            await callback.answer()
            return
        draft.day, draft.time = value, None  # другой день — время выбираем заново
        await step_done(draft, "date", bot, state, **nav)
    elif action == "time":
        draft.time = value
        if draft.starts_at is None or not bk.is_slot_available(draft.starts_at):
            draft.time = None
            await callback.answer("Это время уже недоступно", show_alert=True)
            draft.step = "time"
            await render(bot, state=state, draft=draft, **nav)
            return
        await step_done(draft, "time", bot, state, **nav)
    elif action == "guests":
        guests = int(value) if value.isdigit() else 0
        if not 1 <= guests <= config.BOOKING_MAX_GUESTS:
            await callback.answer()
            return
        draft.guests = guests
        await step_done(draft, "guests", bot, state, **nav)
    elif action == "name":
        draft.name = bk.clean_name(full_name) or bk.clean_name(callback.from_user.full_name)
        if not draft.name:
            await callback.answer("Напишите имя сообщением", show_alert=True)
            return
        await step_done(draft, "name", bot, state, **nav)
    elif action == "phone":
        user = await users.get_user(callback.from_user.id)
        if not user or not user.phone:
            await callback.answer("Напишите номер сообщением", show_alert=True)
            return
        draft.phone = user.phone
        await step_done(draft, "phone", bot, state, **nav)
    elif action == "confirm":
        await submit(callback, state, bot, draft)
        return
    await callback.answer()


@router.message(BookingForm.name, F.text)
async def on_name(message: Message, state: FSMContext, bot: Bot) -> None:
    await screen.delete_user_input(message)
    draft, full_name = await load(state)
    if draft is None:
        await state.clear()
        return
    name = bk.clean_name(message.text)
    nav = dict(user_id=message.from_user.id, chat_id=message.chat.id, full_name=full_name)
    if name is None:
        await render(bot, state=state, draft=draft, notice=f"Имя — от {bk.NAME_MIN} до {bk.NAME_MAX} символов.", **nav)
        return
    draft.name = name
    await step_done(draft, "name", bot, state, **nav)


@router.message(BookingForm.phone, F.text | F.contact)
async def on_phone(message: Message, state: FSMContext, bot: Bot) -> None:
    await screen.delete_user_input(message)
    draft, full_name = await load(state)
    if draft is None:
        await state.clear()
        return
    raw = message.contact.phone_number if message.contact else message.text
    if raw and message.contact and not raw.startswith("+"):
        raw = "+" + raw
    phone = normalize_phone(raw or "")
    nav = dict(user_id=message.from_user.id, chat_id=message.chat.id, full_name=full_name)
    if phone is None:
        await render(bot, state=state, draft=draft, notice="Не похоже на номер телефона. Пример: +7 999 123-45-67",
                     **nav)
        return
    draft.phone = phone
    await step_done(draft, "phone", bot, state, **nav)


@router.message(BookingForm.buttons)
@router.message(BookingForm.name)
@router.message(BookingForm.phone)
async def on_unexpected(message: Message, state: FSMContext, bot: Bot) -> None:
    await screen.delete_user_input(message)
    draft, full_name = await load(state)
    if draft is None:
        await state.clear()
        return
    hint = "Пожалуйста, отправьте текстовое сообщение." if draft.step in INPUT_STATES \
        else "Пожалуйста, выберите вариант кнопкой 👇"
    await render(bot, message.chat.id, message.from_user.id, state, draft, notice=hint, full_name=full_name)


async def submit(callback: CallbackQuery, state: FSMContext, bot: Bot, draft: BookingDraft) -> None:
    user_id = callback.from_user.id
    _, full_name = await load(state)
    if not all(draft.is_filled(s) for s in bk.STEPS[:-1]):
        draft.step = draft.advance()
        await render(bot, callback.message.chat.id, user_id, state, draft, message=callback.message,
                     full_name=full_name)
        await callback.answer()
        return
    if not bk.is_slot_available(draft.starts_at):
        draft.time, draft.step = None, "time"
        await render(bot, callback.message.chat.id, user_id, state, draft, message=callback.message,
                     full_name=full_name, notice="Пока вы заполняли заявку, это время стало недоступно.")
        await callback.answer()
        return

    await state.clear()  # до записи в БД — повторное нажатие не создаст вторую бронь
    booking_id = await bookings_db.create_booking(
        user_id=user_id, starts_at=draft.starts_at, guests=draft.guests, name=draft.name, phone=draft.phone,
    )
    await users.save_contact_details(user_id, phone=draft.phone)
    booking = await bookings_db.get_booking(booking_id)
    await send_to_admins(bot, booking)
    logger.info("Новая бронь №%s на %s", booking_id, draft.starts_at)

    text = ("📅 <b>Заявка отправлена!</b>\n<blockquote>" + bk.summary(draft) + "</blockquote>\n"
            "⏳ Ждём подтверждения администратора — пришлём уведомление 🙌")
    await screen.show(bot, callback.message.chat.id, text, kb.done(), picture=screen.banner("booking"),
                      message=callback.message)
    await callback.answer("Заявка отправлена")


# ---------------------------------------------------------------------------
# Администратор
# ---------------------------------------------------------------------------

async def _admin_card(booking: Booking) -> str:
    user = await users.get_user(booking.user_id)
    return bk.admin_card(booking, user.username if user else None)


async def send_to_admins(bot: Bot, booking: Booking) -> None:
    text = await _admin_card(booking)
    sent = []
    for chat_id in booking_recipients():
        try:
            message = await bot.send_message(chat_id, text, reply_markup=kb.admin_decision(booking))
            sent.append((chat_id, message.message_id))
        except TelegramAPIError:
            logger.exception("Не удалось отправить заявку на бронь №%s в чат %s", booking.id, chat_id)
    if not sent:
        logger.error("Заявку на бронь №%s некому подтвердить — проверьте ADMIN_ID / STAFF_CHAT_ID", booking.id)
    await bookings_db.set_admin_messages(booking.id, sent)


async def refresh_admin_cards(bot: Bot, booking: Booking) -> None:
    text = await _admin_card(booking)
    for chat_id, message_id in booking.admin_messages:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                        reply_markup=kb.admin_decision(booking))
        except TelegramAPIError as exc:
            if "message is not modified" not in str(exc):
                logger.warning("Не удалось обновить карточку брони №%s: %s", booking.id, exc)


admin_router = Router(name="booking_admin")


@admin_router.callback_query(BookAdminCb.filter())
async def on_admin_decision(callback: CallbackQuery, callback_data: BookAdminCb, bot: Bot) -> None:
    if callback.message is None or callback.message.chat.id not in booking_recipients():
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    new_status = BookingStatus.CONFIRMED if callback_data.a == "ok" else BookingStatus.REJECTED
    changed = await bookings_db.update_status(
        callback_data.id, new_status, expected=BookingStatus.PENDING, decided_by=callback.from_user.full_name,
    )
    booking = await bookings_db.get_booking(callback_data.id)
    if booking is None:
        await callback.answer("Бронь не найдена", show_alert=True)
        return
    await refresh_admin_cards(bot, booking)
    if not changed:
        await callback.answer("По этой брони уже принято решение", show_alert=True)
        return

    text = bk.client_notification(booking)
    try:
        await bot.send_message(booking.user_id, text)
    except TelegramForbiddenError:
        await users.mark_blocked(booking.user_id)
    except TelegramAPIError:
        logger.exception("Не удалось уведомить гостя о брони №%s", booking.id)
    if new_status == BookingStatus.CONFIRMED:
        scheduler.schedule_booking_reminder(booking)
    await callback.answer("Гость уведомлён")
