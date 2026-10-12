"""Оформление заказа: способ получения → данные → комментарий → оплата → подтверждение."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import config
from database import cart, users
from database.models import CartLine, Order, OrderMethod, PaymentMethod
from keyboards import checkout as kb
from keyboards.callbacks import CartCb, CheckoutCb
from orders import checkout as co
from orders import hours, pricing, service
from orders.checkout import Draft
from orders.formatting import when_text
from orders.table import get_active_table
from utils import screen
from utils.format import esc, format_phone, money, normalize_phone
from utils.timeutil import human_datetime, now_local

from .cart import show_cart

logger = logging.getLogger(__name__)
router = Router(name="checkout")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

DRAFT_KEY = "checkout"

# Защита от двойного нажатия «Подтвердить»: заказы одного клиента создаются по очереди
_submit_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


class CheckoutForm(StatesGroup):
    buttons = State()   # шаги с кнопками
    address = State()
    phone = State()
    comment = State()


INPUT_STATES = {"address": CheckoutForm.address, "phone": CheckoutForm.phone, "comment": CheckoutForm.comment}


# ---------------------------------------------------------------------------
# Черновик в FSM
# ---------------------------------------------------------------------------

async def load_draft(state: FSMContext) -> Draft | None:
    data = (await state.get_data()).get(DRAFT_KEY)
    return Draft.from_dict(data) if data else None


async def save_draft(state: FSMContext, draft: Draft) -> None:
    await state.update_data({DRAFT_KEY: draft.to_dict()})


async def draft_or_restart(callback: CallbackQuery, state: FSMContext, bot: Bot) -> Draft | None:
    """Черновик мог потеряться (перезапуск бота) — тогда начинаем из корзины."""
    draft = await load_draft(state)
    if draft is None:
        await callback.answer("Оформление прервалось — начните, пожалуйста, заново", show_alert=True)
        await show_cart(bot, callback)
    return draft


# ---------------------------------------------------------------------------
# Экраны шагов
# ---------------------------------------------------------------------------

def _progress(draft: Draft) -> str:
    if draft.method is None:  # пока не выбран способ получения, число шагов неизвестно
        return "📝 <b>Оформление заказа</b>"
    seq = co.steps(draft)
    position = seq.index(draft.step) + 1 if draft.step in seq else 1
    return f"📝 <b>Оформление заказа</b> · шаг {position} из {len(seq)}"


def _summary(draft: Draft, lines: list[CartLine]) -> tuple[str, int]:
    """Текст экрана подтверждения и итоговая сумма."""
    available = pricing.available_lines(lines)
    items_total = pricing.subtotal(available)
    zone = draft.zone if draft.method == OrderMethod.DELIVERY else None
    fee = pricing.delivery_fee(zone, items_total) if zone else 0
    total = items_total + fee

    rows = ["📋 <b>Проверьте заказ</b>", ""]
    for n, line in enumerate(available, 1):
        qty = f" × {line.qty}" if line.qty > 1 else ""
        rows.append(f"{n}. {esc(pricing.line_title(line))}{qty} — {money(line.total)}")
    rows.append("")

    rows.append(co.METHOD_TITLES[OrderMethod(draft.method)] + (f" · {esc(zone.title)}" if zone else ""))
    if draft.method == OrderMethod.TABLE:
        rows.append(f"🍽 Стол №{draft.table_no}")
    if zone:
        rows.append(f"📍 {esc(draft.address)}")
    if draft.method != OrderMethod.TABLE:
        rows.append(f"🕐 {co.time_label(draft)}")
        rows.append(f"📞 {format_phone(draft.phone)}")
    if draft.method == OrderMethod.PICKUP:
        rows.append(f"🏠 Забрать: {esc(config.VENUE_ADDRESS)}")
    if draft.comment:
        rows.append(f"💬 {esc(draft.comment)}")
    rows.append(co.PAYMENT_TITLES[PaymentMethod(draft.payment)])
    rows.append("")
    rows.append(f"Товары: {money(items_total)}")
    if zone:
        rows.append(f"Доставка: {'бесплатно' if fee == 0 else money(fee)}")
    rows.append(f"<b>Итого: {money(total)}</b>")
    return "\n".join(rows), total


async def render(
    bot: Bot,
    chat_id: int,
    user_id: int,
    state: FSMContext,
    draft: Draft,
    *,
    message: Message | None = None,
    notice: str | None = None,
    show_slots: bool = False,
) -> None:
    lines = await cart.get_cart(user_id)
    items_total = pricing.subtotal(lines)
    step = draft.step
    head = _progress(draft)
    keyboard: InlineKeyboardMarkup

    if step == "method":
        body = "Как хотите получить заказ?"
        keyboard = kb.methods(co.available_methods())

    elif step == "zone":
        zone_lines = []
        for zone in config.DELIVERY_ZONES:
            fee = pricing.delivery_fee(zone, items_total)
            fee_text = "бесплатно" if fee == 0 else money(fee)
            conditions = f"💰 Доставка {fee_text} · заказ от {money(zone.min_order)}"
            if zone.free_from and fee:
                conditions += f" · бесплатно от {money(zone.free_from)}"
            zone_lines.append(
                f"<b>{esc(zone.title)}</b>\n{esc(zone.description)}\n{conditions}\n⏱ ≈{zone.eta_minutes} мин"
            )
        body = "🚚 Выберите зону доставки:\n\n" + "\n\n".join(zone_lines)
        keyboard = kb.zones(items_total)

    elif step == "address":
        user = await users.get_user(user_id)
        body = "📍 Напишите адрес доставки одним сообщением:\nулица, дом, подъезд, этаж, квартира."
        if user and user.last_address:
            body += "\n\nИли выберите прошлый адрес кнопкой 👇"
        keyboard = kb.address(user.last_address if user else None)

    elif step == "time":
        now = now_local()
        if draft.method == OrderMethod.DELIVERY:
            asap = co.asap_available(now)
            has_choice = asap
            if not show_slots and has_choice:
                zone = draft.zone
                eta = f" — привезём примерно за {zone.eta_minutes} минут" if zone else ""
                body = f"🕐 Когда доставить?\n\n⚡ Как можно скорее{eta}\n🕐 Или ко времени"
                keyboard = kb.time_delivery(asap)
        else:
            quick = co.quick_pickup_options(now)
            has_choice = bool(quick)
            if not show_slots and has_choice:
                body = f"🕐 Когда заберёте заказ?\n\n🏠 Адрес: {esc(config.VENUE_ADDRESS)}"
                keyboard = kb.time_pickup(quick)
        if show_slots or not has_choice:
            slots = hours.time_slots(lead_minutes=co.lead_minutes(draft.method), now=now)
            if not slots:
                body = "😔 К сожалению, в ближайшие дни свободного времени нет. Позвоните нам: " + esc(config.VENUE_PHONE)
            elif not has_choice:
                opening = hours.next_opening(now)
                closed = f"Сейчас мы не принимаем заказы, откроемся {human_datetime(opening)}. " if opening else ""
                body = f"🕐 {closed}Выберите удобное время — приготовим к нему:"
            else:
                body = "🕐 Выберите время:"
            keyboard = kb.slots(slots, now.date(), back_to_choice=has_choice)

    elif step == "phone":
        user = await users.get_user(user_id)
        body = "📞 Напишите номер телефона для связи, например +7 999 123-45-67."
        if user and user.phone:
            body += "\n\nИли используйте прошлый номер 👇"
        keyboard = kb.phone(user.phone if user else None)

    elif step == "comment":
        body = (
            "💬 Комментарий к заказу?\n\n"
            "Например: «без лука», «код домофона 12», «нужна сдача с 5000».\n"
            "Напишите его сообщением или нажмите «Без комментария»."
        )
        keyboard = kb.comment()

    elif step == "payment":
        body = "💳 Как будете оплачивать?"
        keyboard = kb.payment(co.payment_options(draft.method))

    else:  # confirm
        summary, total = _summary(draft, lines)
        body = summary
        keyboard = kb.confirm(total, draft.payment == PaymentMethod.ONLINE)

    text = f"{head}\n\n{body}"
    if notice:
        text = f"⚠️ {notice}\n\n{text}"

    await save_draft(state, draft)
    await state.set_state(INPUT_STATES.get(step, CheckoutForm.buttons))
    await screen.show(bot, chat_id, text, keyboard, message=message)


async def go_to(step: str, draft: Draft, bot: Bot, state: FSMContext, *, user_id: int, chat_id: int,
                message: Message | None = None, notice: str | None = None) -> None:
    draft.step = step
    await render(bot, chat_id, user_id, state, draft, message=message, notice=notice)


async def complete_step(step: str, draft: Draft, bot: Bot, state: FSMContext, *, user_id: int, chat_id: int,
                        message: Message | None = None) -> None:
    """Шаг заполнен — переходим к следующему незаполненному."""
    draft.step = step
    await go_to(co.advance(draft), draft, bot, state, user_id=user_id, chat_id=chat_id, message=message)


# ---------------------------------------------------------------------------
# Старт и навигация
# ---------------------------------------------------------------------------

@router.callback_query(CartCb.filter(F.a == "checkout"))
async def on_checkout(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    user_id = callback.from_user.id
    if not config.FEATURES.ordering:
        await callback.answer("Онлайн-заказ сейчас недоступен", show_alert=True)
        return

    lines = await cart.get_cart(user_id)
    unavailable = [l for l in lines if not l.item.is_available]
    if unavailable:
        for line in unavailable:
            await cart.remove_line(user_id, line.id)
        names = ", ".join(l.item.title for l in unavailable)
        await show_cart(bot, callback, notice=f"⚠️ Закончилось: {esc(names)}. Мы убрали это из корзины.")
        await callback.answer()
        return
    if not lines:
        await show_cart(bot, callback)
        await callback.answer()
        return

    table_no = await get_active_table(user_id)
    if not table_no and not config.FEATURES.remote_ordering:
        await callback.answer("Заказ доступен только за столиком — отсканируйте QR-код на столе", show_alert=True)
        return

    draft = co.start(table_no)
    await render(bot, callback.message.chat.id, user_id, state, draft, message=callback.message)
    await callback.answer()


@router.callback_query(CheckoutCb.filter(F.a == "back"))
async def on_back(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    previous = co.prev_step(draft)
    if previous is None:
        await state.clear()
        await show_cart(bot, callback)
    else:
        await go_to(previous, draft, bot, state, user_id=callback.from_user.id,
                    chat_id=callback.message.chat.id, message=callback.message)
    await callback.answer()


# ---------------------------------------------------------------------------
# Шаги с кнопками
# ---------------------------------------------------------------------------

@router.callback_query(CheckoutCb.filter(F.a == "method"))
async def on_method(callback: CallbackQuery, callback_data: CheckoutCb, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    try:
        method = OrderMethod(callback_data.v)
    except ValueError:
        method = None
    if method not in co.available_methods():
        await callback.answer("Этот способ сейчас недоступен", show_alert=True)
        return
    co.set_method(draft, method)
    await complete_step("method", draft, bot, state, user_id=callback.from_user.id,
                        chat_id=callback.message.chat.id, message=callback.message)
    await callback.answer()


@router.callback_query(CheckoutCb.filter(F.a == "zone"))
async def on_zone(callback: CallbackQuery, callback_data: CheckoutCb, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    zone = config.get_zone(int(callback_data.v)) if callback_data.v.isdigit() else None
    if zone is None:
        await callback.answer("Зона не найдена", show_alert=True)
        return
    items_total = pricing.subtotal(await cart.get_cart(callback.from_user.id))
    shortfall = pricing.min_order_shortfall(zone, items_total)
    if shortfall:
        await callback.answer(
            f"Минимальный заказ в эту зону — {money(zone.min_order)}.\nДобавьте ещё на {money(shortfall)} 🙏",
            show_alert=True,
        )
        return
    draft.zone_id = zone.id
    await complete_step("zone", draft, bot, state, user_id=callback.from_user.id,
                        chat_id=callback.message.chat.id, message=callback.message)
    await callback.answer()


@router.callback_query(CheckoutCb.filter(F.a == "addr"))
async def on_saved_address(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    user = await users.get_user(callback.from_user.id)
    if not user or not user.last_address:
        await callback.answer("Напишите адрес сообщением", show_alert=True)
        return
    draft.address = user.last_address
    await complete_step("address", draft, bot, state, user_id=callback.from_user.id,
                        chat_id=callback.message.chat.id, message=callback.message)
    await callback.answer()


@router.callback_query(CheckoutCb.filter(F.a.in_({"slots", "time_menu"})))
async def on_time_menu(callback: CallbackQuery, callback_data: CheckoutCb, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    draft.step = "time"
    await render(bot, callback.message.chat.id, callback.from_user.id, state, draft,
                 message=callback.message, show_slots=callback_data.a == "slots")
    await callback.answer()


@router.callback_query(CheckoutCb.filter(F.a == "time"))
async def on_time(callback: CallbackQuery, callback_data: CheckoutCb, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    draft.time = callback_data.v
    try:
        error = co.validate_time(draft)
    except ValueError:
        error = "Не удалось распознать время."
    if error:
        draft.time = None
        await callback.answer(error, show_alert=True)
        await go_to("time", draft, bot, state, user_id=callback.from_user.id,
                    chat_id=callback.message.chat.id, message=callback.message)
        return
    await complete_step("time", draft, bot, state, user_id=callback.from_user.id,
                        chat_id=callback.message.chat.id, message=callback.message)
    await callback.answer()


@router.callback_query(CheckoutCb.filter(F.a == "phone"))
async def on_saved_phone(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    user = await users.get_user(callback.from_user.id)
    if not user or not user.phone:
        await callback.answer("Напишите номер сообщением", show_alert=True)
        return
    draft.phone = user.phone
    await complete_step("phone", draft, bot, state, user_id=callback.from_user.id,
                        chat_id=callback.message.chat.id, message=callback.message)
    await callback.answer()


@router.callback_query(CheckoutCb.filter(F.a == "nocomment"))
async def on_no_comment(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    draft.comment = None
    draft.comment_done = True
    await complete_step("comment", draft, bot, state, user_id=callback.from_user.id,
                        chat_id=callback.message.chat.id, message=callback.message)
    await callback.answer()


@router.callback_query(CheckoutCb.filter(F.a == "pay"))
async def on_payment(callback: CallbackQuery, callback_data: CheckoutCb, state: FSMContext, bot: Bot) -> None:
    draft = await draft_or_restart(callback, state, bot)
    if draft is None:
        return
    if callback_data.v not in co.payment_options(draft.method):
        await callback.answer("Этот способ оплаты сейчас недоступен", show_alert=True)
        return
    draft.payment = callback_data.v
    await complete_step("payment", draft, bot, state, user_id=callback.from_user.id,
                        chat_id=callback.message.chat.id, message=callback.message)
    await callback.answer()


# ---------------------------------------------------------------------------
# Шаги с вводом текста
# ---------------------------------------------------------------------------

@router.message(CheckoutForm.address, F.text)
async def on_address_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await screen.delete_user_input(message)
    draft = await load_draft(state)
    if draft is None:
        await state.clear()
        return
    address = co.clean_address(message.text)
    if address is None:
        await go_to("address", draft, bot, state, user_id=message.from_user.id, chat_id=message.chat.id,
                    notice=f"Адрес должен быть от {co.ADDRESS_MIN} до {co.ADDRESS_MAX} символов.")
        return
    draft.address = address
    await complete_step("address", draft, bot, state, user_id=message.from_user.id, chat_id=message.chat.id)


@router.message(CheckoutForm.phone, F.text | F.contact)
async def on_phone_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await screen.delete_user_input(message)
    draft = await load_draft(state)
    if draft is None:
        await state.clear()
        return
    raw = message.contact.phone_number if message.contact else message.text
    if raw and message.contact and not raw.startswith("+"):
        raw = "+" + raw
    phone = normalize_phone(raw or "")
    if phone is None:
        await go_to("phone", draft, bot, state, user_id=message.from_user.id, chat_id=message.chat.id,
                    notice="Не похоже на номер телефона. Пример: +7 999 123-45-67")
        return
    draft.phone = phone
    await complete_step("phone", draft, bot, state, user_id=message.from_user.id, chat_id=message.chat.id)


@router.message(CheckoutForm.comment, F.text)
async def on_comment_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await screen.delete_user_input(message)
    draft = await load_draft(state)
    if draft is None:
        await state.clear()
        return
    draft.comment = co.clean_comment(message.text)
    draft.comment_done = True
    await complete_step("comment", draft, bot, state, user_id=message.from_user.id, chat_id=message.chat.id)


@router.message(CheckoutForm.buttons)
@router.message(CheckoutForm.address)
@router.message(CheckoutForm.phone)
@router.message(CheckoutForm.comment)
async def on_unexpected_input(message: Message, state: FSMContext, bot: Bot) -> None:
    """Стикер, фото или текст там, где ждём кнопку, — не теряем оформление, а подсказываем."""
    await screen.delete_user_input(message)
    draft = await load_draft(state)
    if draft is None:
        await state.clear()
        return
    hint = "Пожалуйста, выберите вариант кнопкой 👇" if draft.step not in INPUT_STATES \
        else "Пожалуйста, отправьте текстовое сообщение."
    await go_to(draft.step, draft, bot, state, user_id=message.from_user.id, chat_id=message.chat.id, notice=hint)


# ---------------------------------------------------------------------------
# Подтверждение
# ---------------------------------------------------------------------------

@router.callback_query(CheckoutCb.filter(F.a == "confirm"))
async def on_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    user_id = callback.from_user.id
    async with _submit_locks[user_id]:
        draft = await load_draft(state)
        if draft is None:
            await callback.answer("Этот заказ уже оформлен или оформление прервалось", show_alert=True)
            return
        await submit(callback, state, bot, draft)


async def submit(callback: CallbackQuery, state: FSMContext, bot: Bot, draft: Draft) -> None:
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    nav = dict(user_id=user_id, chat_id=chat_id, message=callback.message)

    # Пока клиент оформлял, что-то могло измениться: стоп-лист, время, стол
    lines = await cart.get_cart(user_id)
    unavailable = [l for l in lines if not l.item.is_available]
    if unavailable or not lines:
        for line in unavailable:
            await cart.remove_line(user_id, line.id)
        await state.clear()
        names = ", ".join(l.item.title for l in unavailable)
        notice = f"⚠️ Пока вы оформляли, закончилось: {esc(names)}. Проверьте корзину." if names else None
        await show_cart(bot, callback, notice=notice)
        await callback.answer()
        return

    for step in co.steps(draft)[:-1]:
        if not co.is_filled(draft, step):
            await go_to(step, draft, bot, state, **nav, notice="Заполните, пожалуйста, этот шаг.")
            await callback.answer()
            return

    if draft.method == OrderMethod.TABLE and await get_active_table(user_id) != draft.table_no:
        await state.clear()
        await show_cart(bot, callback, notice="⚠️ Сессия стола истекла — отсканируйте QR-код на столе ещё раз.")
        await callback.answer()
        return

    if draft.method == OrderMethod.DELIVERY:
        shortfall = pricing.min_order_shortfall(draft.zone, pricing.subtotal(lines))
        if shortfall:
            await state.clear()
            await show_cart(bot, callback, notice=f"⚠️ До минимальной суммы заказа не хватает {money(shortfall)}.")
            await callback.answer()
            return

    error = co.validate_time(draft)
    if error:
        if draft.method == OrderMethod.TABLE:
            await state.clear()
            await show_cart(bot, callback, notice=f"⚠️ {error}")
        else:
            draft.time = None
            await go_to("time", draft, bot, state, **nav, notice=error)
        await callback.answer()
        return

    if draft.payment == PaymentMethod.ONLINE:
        await callback.answer("Онлайн-оплата пока недоступна", show_alert=True)
        return

    order = await service.place_order(
        bot, user_id=user_id, customer_name=callback.from_user.full_name, draft=draft, lines=lines,
    )
    await state.clear()
    await show_order_placed(bot, chat_id, order, message=callback.message)
    await callback.answer("Заказ оформлен 🎉")


async def show_order_placed(bot: Bot, chat_id: int, order: Order, message: Message | None = None) -> None:
    rows = [
        f"🎉 <b>Заказ №{order.id} оформлен!</b>",
        "",
        "Мы передали его в заведение. Как только заказ примут, пришлём уведомление, "
        "а дальше будем сообщать о каждом шаге.",
        "",
        f"💰 Сумма: <b>{money(order.total)}</b>",
    ]
    if order.method == OrderMethod.TABLE:
        rows.append(f"🍽 Принесём к столу №{order.table_no}")
    else:
        rows.append(f"🕐 {when_text(order)}")
    await screen.show(bot, chat_id, "\n".join(rows), kb.done(), message=message)
