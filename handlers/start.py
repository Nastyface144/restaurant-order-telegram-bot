"""/start, главное меню, контакты и вход за столик по QR-коду."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from database import cart, users
from keyboards import client as kb
from keyboards.callbacks import Nav
from orders import hours
from orders.table import get_active_table, parse_table_payload
from utils import screen
from utils.format import esc, money
from utils.timeutil import human_datetime, now_local

router = Router(name="start")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")


def venue_status_text() -> str:
    now = now_local()
    interval = hours.current_interval(now)
    if interval and hours.accepts_orders_now(now):
        return f"🟢 Открыто до {interval[1]:%H:%M}"
    opening = hours.next_opening(now)
    when = f"Откроемся {human_datetime(opening)}." if opening else "Временно не работаем."
    if interval:
        text = f"🟡 Скоро закрываемся — заказы на сегодня больше не принимаем. {when}"
    else:
        text = f"🔴 Сейчас закрыто. {when}"
    if config.FEATURES.remote_ordering and opening:
        text += "\nЗаказ можно оформить заранее — ко времени после открытия."
    return text


def main_menu_text(table_no: int | None, notice: str | None = None) -> str:
    lines = [f"🍕 <b>{esc(config.VENUE_NAME)}</b>", esc(config.VENUE_TAGLINE), "", venue_status_text()]
    if table_no:
        lines += ["", f"🍽 Вы за столом <b>№{table_no}</b> — заказ принесём прямо к столу, оплата на месте."]
    if notice:
        lines += ["", notice]
    return "\n".join(lines)


async def show_main_menu(bot: Bot, chat_id: int, user_id: int, message: Message | None = None,
                         force_new: bool = False, notice: str | None = None) -> None:
    table_no = await get_active_table(user_id)
    count = await cart.count_cart_items(user_id)
    await screen.show(
        bot, chat_id, main_menu_text(table_no, notice), kb.main_menu(count, table_no is not None),
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
async def on_contacts(callback: CallbackQuery, bot: Bot) -> None:
    text = (
        f"📍 <b>{esc(config.VENUE_NAME)}</b>\n\n"
        f"🏠 {esc(config.VENUE_ADDRESS)}\n"
        f"📞 {esc(config.VENUE_PHONE)}\n\n"
        f"🕐 <b>Часы работы</b>\n{hours.format_hours()}\n\n"
        f"{venue_status_text()}"
    )
    if config.FEATURES.delivery:
        zones = "\n".join(
            f"• {esc(z.title)}: доставка {money(z.price)}, заказ от {money(z.min_order)}"
            for z in config.DELIVERY_ZONES
        )
        text += f"\n\n🚚 <b>Доставка</b>\n{zones}"
    await screen.show(bot, callback.message.chat.id, text, kb.contacts(), message=callback.message)
    await callback.answer()
