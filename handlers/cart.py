"""Корзина: количество, удаление, итог и подсказки про доставку."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import config
from database import cart
from keyboards import cart as kb
from keyboards.callbacks import CartCb, Nav
from orders import pricing
from orders.table import get_active_table
from utils import screen
from utils.format import esc, money

router = Router(name="cart")
router.callback_query.filter(F.message.chat.type == "private")


def delivery_hints(items_total: int) -> list[str]:
    """Коротко о доставке и подсказка, сколько добавить до бесплатной."""
    if not config.FEATURES.delivery or not config.DELIVERY_ZONES:
        return []
    zones = config.DELIVERY_ZONES
    min_order = min(z.min_order for z in zones)
    if items_total < min_order:
        hint = f"🛵 Доставка — от {money(min_order)}: добавьте ещё {money(min_order - items_total)}"
        if config.FEATURES.pickup:
            hint += "\n🏃 Самовывоз — без минимальной суммы"
        return [hint]

    free_zones = [z for z in zones if z.free_from]
    reached = [z for z in free_zones if items_total >= z.free_from]
    if reached:
        names = ", ".join(z.title.split(" — ")[0].lower() for z in reached)
        return [f"🎁 Доставка бесплатно ({names})"]
    price = min(z.price for z in zones)
    lines = [f"🛵 Доставка от {money(price)}"]
    if free_zones:
        nearest = min(free_zones, key=lambda z: z.free_from)
        lines.append(f"💡 Ещё {money(nearest.free_from - items_total)} — и доставим бесплатно")
    return lines


def cart_text(lines, table_no: int | None, notice: str | None = None) -> str:
    count = sum(line.qty for line in lines if line.item.is_available)
    rows = [f"<b>Корзина</b> · {count} шт", ""]
    blocks = []
    for line in lines:
        title = f"<b>{esc(line.item.title)}</b>"
        options = esc(pricing.line_title(line)[len(line.item.title):].lstrip(", "))
        if options:
            title += f" · {options}"
        if not line.item.is_available:
            blocks.append(f"⛔ <s>{esc(line.item.title)}</s> — закончилось, не войдёт в заказ")
        elif line.qty == 1:
            blocks.append(f"{title}\n{money(line.total)}")
        else:
            blocks.append(f"{title}\n{line.qty} × {money(line.unit_price)} = <b>{money(line.total)}</b>")
    rows.append("<blockquote>" + "\n\n".join(blocks) + "</blockquote>")

    items_total = pricing.subtotal(lines)
    rows.append(f"Итого: <b>{money(items_total)}</b>")
    if table_no:
        rows.append(f"🍽 Принесём к столу №{table_no}, оплата на месте")
    else:
        rows += delivery_hints(items_total)
    if notice:
        rows = [notice, "", *rows]
    return "\n".join(rows)


async def show_cart(bot: Bot, callback: CallbackQuery, notice: str | None = None) -> None:
    user_id = callback.from_user.id
    lines = await cart.get_cart(user_id)
    chat_id = callback.message.chat.id
    picture = screen.banner("cart")

    if not lines:
        text = "<b>Корзина пуста</b>\nЗагляните в меню — там много вкусного 🍕"
        if notice:
            text = f"{notice}\n\n{text}"
        await screen.show(bot, chat_id, text, kb.empty_cart(), picture=picture, message=callback.message)
        return

    table_no = await get_active_table(user_id)
    await screen.show(bot, chat_id, cart_text(lines, table_no, notice), kb.cart(lines, pricing.subtotal(lines)),
                      picture=picture, message=callback.message)


@router.callback_query(Nav.filter(F.to == "cart"))
async def on_cart(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await show_cart(bot, callback)
    await callback.answer()


@router.callback_query(CartCb.filter(F.a.in_({"inc", "dec"})))
async def on_change_qty(callback: CallbackQuery, callback_data: CartCb, bot: Bot) -> None:
    delta = 1 if callback_data.a == "inc" else -1
    await cart.change_qty(callback.from_user.id, callback_data.line, delta)
    await show_cart(bot, callback)
    await callback.answer()


@router.callback_query(CartCb.filter(F.a == "del"))
async def on_delete_line(callback: CallbackQuery, callback_data: CartCb, bot: Bot) -> None:
    await cart.remove_line(callback.from_user.id, callback_data.line)
    await show_cart(bot, callback)
    await callback.answer("Убрали из корзины")


@router.callback_query(CartCb.filter(F.a == "clear"))
async def on_clear(callback: CallbackQuery, bot: Bot) -> None:
    await screen.show(bot, callback.message.chat.id, "<b>Очистить корзину?</b>\nВсе позиции будут удалены.",
                      kb.confirm_clear(), picture=screen.banner("cart"), message=callback.message)
    await callback.answer()


@router.callback_query(CartCb.filter(F.a == "clear_yes"))
async def on_clear_confirmed(callback: CallbackQuery, bot: Bot) -> None:
    await cart.clear_cart(callback.from_user.id)
    await show_cart(bot, callback)
    await callback.answer("Корзина очищена")
