"""Счёт на оплату заказа."""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

import config
from database.models import Order
from keyboards.callbacks import PayCb
from utils import screen
from utils.format import money, truncate

PAYLOAD_PREFIX = "order:"


def is_test_mode() -> bool:
    """Тестовые токены ЮKassa из @BotFather выглядят как 123456:TEST:abc."""
    return ":TEST:" in config.PAYMENT_TOKEN


def make_payload(order_id: int) -> str:
    return f"{PAYLOAD_PREFIX}{order_id}"


def parse_payload(payload: str | None) -> int | None:
    if not payload or not payload.startswith(PAYLOAD_PREFIX):
        return None
    raw = payload[len(PAYLOAD_PREFIX):]
    return int(raw) if raw.isdigit() else None


def to_minor(amount: int) -> int:
    """Telegram принимает суммы в минимальных единицах валюты (копейках)."""
    return amount * 100


def build_prices(order: Order) -> list[LabeledPrice]:
    prices = [
        LabeledPrice(
            label=truncate(item.full_title + (f" × {item.qty}" if item.qty > 1 else ""), 64),
            amount=to_minor(item.total),
        )
        for item in order.items
    ]
    if order.delivery_fee:
        prices.append(LabeledPrice(label="Доставка", amount=to_minor(order.delivery_fee)))
    return prices


def invoice_keyboard(order: Order) -> InlineKeyboardMarkup:
    # Кнопка оплаты обязана быть первой
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {money(order.total)}", pay=True)],
        [InlineKeyboardButton(text="✖️ Отменить и вернуться в корзину",
                              callback_data=PayCb(a="cancel", order=order.id).pack())],
    ])


async def send_invoice(bot: Bot, chat_id: int, order: Order) -> Message:
    description = ", ".join(i.title for i in order.items)
    if is_test_mode():
        description += ". Тестовый режим: оплатите тестовой картой 5555 5555 5555 4477, срок — любой будущий, CVC — любой."
    return await bot.send_invoice(
        chat_id=chat_id,
        title=truncate(f"Заказ №{order.id} · {config.VENUE_NAME}", 32),
        description=truncate(description, 255),
        payload=make_payload(order.id),
        provider_token=config.PAYMENT_TOKEN,
        currency=config.CURRENCY,
        prices=build_prices(order),
        reply_markup=invoice_keyboard(order),
    )


async def start_payment(bot: Bot, chat_id: int, order: Order) -> None:
    """Счёт приходит отдельным сообщением (отредактировать в него экран нельзя),
    поэтому прошлый экран удаляем, а счёт становится текущим «экраном»."""
    old_screen = screen.current_screen_id(chat_id)
    invoice = await send_invoice(bot, chat_id, order)
    screen.remember(invoice)
    if old_screen and old_screen != invoice.message_id:
        try:
            await bot.delete_message(chat_id, old_screen)
        except TelegramAPIError:
            pass  # старое сообщение могло уже исчезнуть
