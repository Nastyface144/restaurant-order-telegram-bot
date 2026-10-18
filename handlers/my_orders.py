"""«Мои заказы»: история, детали заказа, повтор."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from database import orders as orders_db
from keyboards import orders as kb
from keyboards.callbacks import Nav, OrdersCb
from orders.formatting import client_card
from orders.repeat import repeat_order
from utils import screen
from utils.format import esc, plural

from .cart import show_cart

router = Router(name="my_orders")
router.callback_query.filter(F.message.chat.type == "private")

HISTORY_LIMIT = 10


@router.callback_query(Nav.filter(F.to == "orders"))
async def on_orders(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    orders = await orders_db.get_user_orders(callback.from_user.id, limit=HISTORY_LIMIT)
    if orders:
        text = "<b>Мои заказы</b>\nНажмите на заказ — покажем статус и можно повторить в одно касание 👇"
    else:
        text = "<b>Мои заказы</b>\nВы ещё ничего не заказывали. Самое время начать 🍕"
    await screen.show(bot, callback.message.chat.id, text, kb.orders_list(orders), picture=screen.banner("orders"),
                      message=callback.message)
    await callback.answer()


async def _own_order(callback: CallbackQuery, order_id: int):
    order = await orders_db.get_order(order_id)
    if order is None or order.user_id != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return None
    return order


@router.callback_query(OrdersCb.filter(F.a == "view"))
async def on_order(callback: CallbackQuery, callback_data: OrdersCb, bot: Bot) -> None:
    order = await _own_order(callback, callback_data.id)
    if order is None:
        return
    await screen.show(bot, callback.message.chat.id, client_card(order), kb.order_details(order),
                      picture=screen.banner("orders"),
                      message=callback.message)
    await callback.answer()


@router.callback_query(OrdersCb.filter(F.a == "repeat"))
async def on_repeat(callback: CallbackQuery, callback_data: OrdersCb, bot: Bot) -> None:
    order = await _own_order(callback, callback_data.id)
    if order is None:
        return
    result = await repeat_order(callback.from_user.id, order)

    notes = []
    if result.added:
        notes.append(f"🔁 Добавили в корзину {result.added} {plural(result.added, 'позицию', 'позиции', 'позиций')} "
                     f"из заказа №{order.id}. Цены — актуальные.")
    if result.unavailable:
        notes.append("⛔ Сейчас недоступно: " + esc(", ".join(result.unavailable)))
    if result.changed:
        notes.append("ℹ️ Некоторых добавок больше нет в меню: " + esc(", ".join(result.changed)))
    if not result.added:
        notes.insert(0, "😔 Повторить не получилось — этих блюд сейчас нет в меню.")
    await show_cart(bot, callback, notice="\n".join(notes))
    await callback.answer()
