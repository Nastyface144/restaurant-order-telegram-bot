"""/start, главный экран, контакты и вход за столик по QR-коду."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from database import cart, users
from database import orders as orders_db
from database.models import Order
from keyboards import client as kb
from keyboards.callbacks import Nav
from orders import hours, pricing
from orders.statuses import ACTIVE_STATUSES
from orders.table import get_active_table, parse_table_payload
from utils import screen
from utils.format import esc, money
from utils.timeutil import human_datetime, now_local

router = Router(name="start")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")


def venue_status_text() -> str:
    """Одна строка: открыто ли сейчас и до скольких."""
    now = now_local()
    interval = hours.current_interval(now)
    if interval and hours.accepts_orders_now(now):
        return f"🟢 Открыто до {interval[1]:%H:%M}"
    opening = hours.next_opening(now)
    when = f"откроемся {human_datetime(opening)}" if opening else "временно не работаем"
    if interval:
        return f"🟡 Заказы на сегодня закончились, {when}"
    return f"🔴 Сейчас закрыто, {when}"


def delivery_terms() -> str:
    """«🛵 Доставка ≈45 мин · 199 ₽, бесплатно от 2 000 ₽»."""
    text = f"🛵 Доставка ≈{config.DELIVERY_ETA_MINUTES} мин · {pricing.delivery_price_text(config.DELIVERY_PRICE)}"
    if config.DELIVERY_PRICE and config.DELIVERY_FREE_FROM:
        text += f", бесплатно от {money(config.DELIVERY_FREE_FROM)}"
    return text


def _delivery_hint() -> str | None:
    return delivery_terms() if config.FEATURES.delivery else None


def main_menu_text(table_no: int | None, accepting: bool, active_order: Order | None,
                   notice: str | None = None) -> str:
    lines = [f"<b>{esc(config.VENUE_NAME)}</b>", venue_status_text()]
    if table_no:
        lines += ["", f"🍽 Вы за столом <b>№{table_no}</b>",
                  "Выберите блюда — принесём прямо к столу, оплата на месте."]
    elif accepting:
        hint = _delivery_hint()
        lines += ["", esc(config.VENUE_TAGLINE)] + ([hint] if hint else [])
    elif config.FEATURES.remote_ordering:
        lines += ["", "Закажите заранее — приготовим ко времени, когда откроемся 🙌"]
    if active_order:
        lines += ["", f"📦 Ваш заказ №{active_order.id} — нажмите, чтобы посмотреть статус"]
    if notice:
        lines += ["", notice]
    return "\n".join(lines)


async def _active_order(user_id: int) -> Order | None:
    for order in await orders_db.get_user_orders(user_id, limit=3):
        if order.status in ACTIVE_STATUSES:
            return order
    return None


async def show_main_menu(bot: Bot, chat_id: int, user_id: int, message: Message | None = None,
                         force_new: bool = False, notice: str | None = None) -> None:
    table_no = await get_active_table(user_id)
    count, total = await cart.cart_summary(user_id)
    accepting = hours.accepts_orders_now()
    active = await _active_order(user_id) if config.FEATURES.ordering else None
    await screen.show(
        bot, chat_id,
        main_menu_text(table_no, accepting, active, notice),
        kb.main_menu(count, total, table_no=table_no, accepting=accepting, active_order=active),
        picture=screen.banner("home" if accepting or table_no else "closed"),
        message=message, force_new=force_new,
    )


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = message.from_user
    # Явно, а не только в мидлвари: снимает флаг «заблокировал бота», если человек вернулся
    await users.upsert_user(user.id, user.full_name, user.username)

    notice = None
    payload = command.args
    if payload and payload.startswith("table_"):
        table_no = parse_table_payload(payload)
        if not config.FEATURES.table:
            notice = "ℹ️ Заказ через бота за столиком сейчас недоступен — позовите официанта, пожалуйста 🙏"
        elif table_no is None:
            notice = "🤔 Не удалось распознать номер стола. Попросите официанта проверить QR-код."
        elif not hours.is_open():
            notice = "ℹ️ Сейчас мы закрыты, поэтому заказ за столиком недоступен."
        else:
            await users.set_table(user.id, table_no)

    await show_main_menu(bot, message.chat.id, user.id, force_new=True, notice=notice)
    await screen.delete_user_input(message)


@router.callback_query(Nav.filter(F.to == "main"))
async def on_main(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await show_main_menu(bot, callback.message.chat.id, callback.from_user.id, message=callback.message)
    await callback.answer()


@router.callback_query(Nav.filter(F.to == "leave_table"))
async def on_leave_table(callback: CallbackQuery, bot: Bot) -> None:
    await users.set_table(callback.from_user.id, None)
    await show_main_menu(bot, callback.message.chat.id, callback.from_user.id, message=callback.message)
    await callback.answer("Хорошо! Теперь можно заказать доставку или самовывоз.")


@router.callback_query(Nav.filter(F.to == "contacts"))
async def on_contacts(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    lines = [
        f"<b>{esc(config.VENUE_NAME)}</b>",
        f"📍 {esc(config.VENUE_ADDRESS)}",
        f"📞 {esc(config.VENUE_PHONE)}",
        "",
        f"🕐 <b>Часы работы</b> · {venue_status_text()}",
        f"<blockquote>{hours.format_hours()}</blockquote>",
    ]
    if config.FEATURES.delivery:
        terms = delivery_terms()
        if config.DELIVERY_MIN_ORDER:
            terms += f"\nМинимальный заказ — {money(config.DELIVERY_MIN_ORDER)}"
        lines += [f"<blockquote>{terms}</blockquote>"]
    await screen.show(bot, callback.message.chat.id, "\n".join(lines), kb.contacts(),
                      picture=screen.banner("contacts"), message=callback.message)
    await callback.answer()
