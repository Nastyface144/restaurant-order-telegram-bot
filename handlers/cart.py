"""Корзина: количество, удаление, итог с доставкой."""

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


def totals_block(items_total: int, table_no: int | None) -> list[str]:
    """Итог корзины с учётом способов получения."""
    lines = [f"💰 Товары: <b>{money(items_total)}</b>"]
    if table_no:
        lines.append(f"🍽 Оплата на месте, за столом №{table_no}")
        return lines

    if config.FEATURES.delivery:
        lines += ["", "🚚 <b>Итого с доставкой:</b>"]
        for zone in config.DELIVERY_ZONES:
            shortfall = pricing.min_order_shortfall(zone, items_total)
            if shortfall:
                lines.append(f"• {esc(zone.title)}: заказ от {money(zone.min_order)} — добавьте ещё {money(shortfall)}")
                continue
            fee = pricing.delivery_fee(zone, items_total)
            fee_text = "доставка бесплатно" if fee == 0 else f"доставка {money(fee)}"
            lines.append(f"• {esc(zone.title)}: <b>{money(items_total + fee)}</b> ({fee_text})")
    if config.FEATURES.pickup:
        lines += ["", f"🏃 Самовывоз: <b>{money(items_total)}</b>"]
    return lines


async def show_cart(bot: Bot, callback: CallbackQuery, notice: str | None = None) -> None:
    user_id = callback.from_user.id
    lines = await cart.get_cart(user_id)
    chat_id = callback.message.chat.id

    if not lines:
        text = "🛒 <b>Корзина пуста</b>\n\nЗагляните в меню — там много вкусного 🍕"
        if notice:
            text = f"{notice}\n\n{text}"
        await screen.show(bot, chat_id, text, kb.empty_cart(), message=callback.message)
        return

    table_no = await get_active_table(user_id)
    text_lines = ["🛒 <b>Корзина</b>", ""]
    for n, line in enumerate(lines, 1):
        title = esc(pricing.line_title(line))
        if not line.item.is_available:
            text_lines.append(f"{n}. ⛔ <s>{title}</s> — закончилось, не войдёт в заказ")
            continue
        if line.qty == 1:
            text_lines.append(f"{n}. {title} — {money(line.total)}")
        else:
            text_lines.append(f"{n}. {title}\n    {money(line.unit_price)} × {line.qty} = {money(line.total)}")

    items_total = pricing.subtotal(lines)
    text_lines += ["", *totals_block(items_total, table_no)]
    if notice:
        text_lines = [notice, "", *text_lines]

    await screen.show(bot, chat_id, "\n".join(text_lines), kb.cart(lines, items_total), message=callback.message)


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
    await screen.show(bot, callback.message.chat.id, "🧹 Очистить корзину?", kb.confirm_clear(),
                      message=callback.message)
    await callback.answer()


@router.callback_query(CartCb.filter(F.a == "clear_yes"))
async def on_clear_confirmed(callback: CallbackQuery, bot: Bot) -> None:
    await cart.clear_cart(callback.from_user.id)
    await show_cart(bot, callback)
    await callback.answer("Корзина очищена")
