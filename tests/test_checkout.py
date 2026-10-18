from datetime import time

import pytest
from aiogram.methods import AnswerCallbackQuery, SendMessage

import config
from database import cart, menu, orders, users
from database.models import OrderMethod, OrderStatus, PaymentMethod

USER = 4004
STAFF = -100500
NB = " "


@pytest.fixture(autouse=True)
def staff_chat(monkeypatch):
    monkeypatch.setattr(config, "STAFF_CHAT_ID", STAFF)


async def add_pizza(qty=2, size="30"):
    categories = await menu.get_categories()
    pizza = (await menu.get_items(categories[0].id))[0]  # Маргарита 30 см = 640
    await cart.add_to_cart(USER, pizza.id, size, [], qty)
    return pizza


async def open_checkout(h, start="/start"):
    await h.send(USER, start)
    await h.click(USER, "Корзина")
    await h.click(USER, "Оформить заказ")


def last_alert(h) -> str:
    return h.session.calls(AnswerCallbackQuery)[-1].text or ""


async def test_delivery_full_flow(harness, always_open):
    await add_pizza()  # 1280 ₽
    await open_checkout(harness)
    assert "шаг" not in harness.screen_text(USER)
    await harness.click(USER, "Доставка")
    assert "шаг 2 из 8" in harness.screen_text(USER)
    await harness.click(USER, "Зона 1")
    assert "Напишите адрес" in harness.screen_text(USER)

    await harness.send(USER, "ул")  # слишком коротко
    assert "Адрес должен быть" in harness.screen_text(USER)
    await harness.send(USER, "ул. Садовая, 5, кв. 12")
    await harness.click(USER, "Как можно скорее")
    await harness.send(USER, "8 (999) 123 45 67")
    await harness.send(USER, "Домофон 12")
    await harness.click(USER, "Наличными")

    text = harness.screen_text(USER)
    assert "Проверьте заказ" in text
    assert "📍 ул. Садовая, 5, кв. 12" in text
    assert f"+7{NB}999{NB}123-45-67" in text
    assert "💬 Домофон 12" in text
    assert f"<b>Итого: 1{NB}430{NB}₽</b>" in text
    # всё это время в чате одно сообщение бота
    assert len(harness.session.chat_messages(USER)) == 1

    await harness.click(USER, "Подтвердить заказ")
    assert "Заказ №1 оформлен" in harness.screen_text(USER)
    order = await orders.get_order(1)
    assert order.status == OrderStatus.NEW
    assert (order.method, order.zone_id, order.delivery_fee, order.total) == (OrderMethod.DELIVERY, 1, 150, 1430)
    assert order.payment_method == PaymentMethod.CASH and order.scheduled_at is None
    assert await cart.get_cart(USER) == []

    # карточка ушла в рабочий чат
    staff_msg = harness.session.last_message(STAFF)
    assert "Заказ №1" in staff_msg["text"] and "Домофон 12" in staff_msg["text"]
    assert order.staff_message_id == staff_msg["message_id"]

    # контакты запомнились
    user = await users.get_user(USER)
    assert (user.phone, user.last_address, user.last_zone_id) == ("+79991234567", "ул. Садовая, 5, кв. 12", 1)


async def test_saved_contacts_and_smart_back(harness, always_open):
    await users.upsert_user(USER, "Иван", None)
    await users.save_contact_details(USER, phone="+79990001122", address="Садовая, 1", zone_id=1)
    await add_pizza()
    await open_checkout(harness)
    await harness.click(USER, "Доставка")
    await harness.click(USER, "Зона 1")
    await harness.click(USER, "📍 Садовая, 1")
    await harness.click(USER, "Как можно скорее")
    await harness.click(USER, "📞")
    await harness.click(USER, "Без комментария")
    await harness.click(USER, "Картой при получении")
    assert "Проверьте заказ" in harness.screen_text(USER)

    # «Назад» с подтверждения → оплата → комментарий; после ввода сразу снова подтверждение
    await harness.click(USER, "Назад")
    assert "Как будете оплачивать" in harness.screen_text(USER)
    await harness.click(USER, "Назад")
    assert "Комментарий к заказу" in harness.screen_text(USER)
    await harness.send(USER, "Без лука")
    assert "Проверьте заказ" in harness.screen_text(USER)
    assert "💬 Без лука" in harness.screen_text(USER)


async def test_back_from_first_step_returns_to_cart(harness, always_open):
    await add_pizza()
    await open_checkout(harness)
    await harness.click(USER, "Назад")
    assert "<b>Корзина</b>" in harness.screen_text(USER)


async def test_zone_min_order(harness, always_open):
    await add_pizza(qty=1, size="25")  # 490 < 700
    await open_checkout(harness)
    await harness.click(USER, "Доставка")
    assert "🔒 Зона 1" in " ".join(harness.buttons(USER))
    await harness.click(USER, "Зона 1")
    assert "Минимальный заказ" in last_alert(harness)
    assert "Выберите зону" in harness.screen_text(USER)


async def test_pickup_quick_time(harness, always_open):
    await add_pizza()
    await open_checkout(harness)
    await harness.click(USER, "Самовывоз")
    assert harness.buttons(USER)[:3] == ["Через 15 мин", "Через 30 мин", "Через 60 мин"]
    await harness.click(USER, "Через 30 мин")
    await harness.send(USER, "+7 912 000-00-00")
    await harness.click(USER, "Без комментария")
    await harness.click(USER, "Наличными")
    assert "Через 30 минут" in harness.screen_text(USER)
    await harness.click(USER, "Подтвердить")
    order = await orders.get_order(1)
    assert order.method == OrderMethod.PICKUP and order.scheduled_at is not None and order.delivery_fee == 0


async def test_pickup_specific_time(harness, always_open):
    await add_pizza()
    await open_checkout(harness)
    await harness.click(USER, "Самовывоз")
    await harness.click(USER, "К конкретному времени")
    slot_buttons = [b for b in harness.buttons(USER) if ":" in b and not b.startswith("📅")]
    assert slot_buttons
    await harness.click(USER, "Назад")  # к выбору «через N минут / ко времени»
    assert "Через 15 мин" in harness.buttons(USER)
    await harness.click(USER, "К конкретному времени")
    await harness.click(USER, slot_buttons[1], exact=True)
    assert "Ваш телефон" in harness.screen_text(USER)


async def test_closed_venue_without_slots(harness, monkeypatch):
    # смена короче, чем время на доставку — заказать на ближайшие дни нельзя
    monkeypatch.setattr(config, "WORKING_HOURS", {d: (time(10), time(10, 30)) for d in range(7)})
    await add_pizza()
    await open_checkout(harness)
    await harness.click(USER, "Доставка")
    await harness.click(USER, "Зона 1")
    await harness.send(USER, "ул. Садовая, 5")
    assert "свободного времени нет" in harness.screen_text(USER)


async def test_closed_venue_offers_time_after_opening(harness, monkeypatch):
    from utils.timeutil import now_local

    tomorrow = (now_local().weekday() + 1) % 7
    monkeypatch.setattr(config, "WORKING_HOURS", {d: None for d in range(7)} | {tomorrow: (time(10), time(22))})
    await add_pizza()
    await open_checkout(harness)
    await harness.click(USER, "Доставка")
    await harness.click(USER, "Зона 1")
    await harness.send(USER, "ул. Садовая, 5")
    text = harness.screen_text(USER)
    assert "откроемся завтра в 10:00" in text and "Выберите удобное время" in text
    buttons = harness.buttons(USER)
    assert "📅 Завтра" in buttons and "Как можно скорее" not in " ".join(buttons)
    assert buttons[buttons.index("📅 Завтра") + 1] == "11:00"  # открытие + время на доставку
    await harness.click(USER, "11:00", exact=True)
    assert "Ваш телефон" in harness.screen_text(USER)


async def test_table_order(harness, always_open):
    await add_pizza(qty=1)
    await open_checkout(harness, start="/start table_5")
    assert "шаг 1 из 2" in harness.screen_text(USER)
    await harness.click(USER, "Без комментария")
    text = harness.screen_text(USER)
    assert "Стол №5" in text and "Оплата на месте" in text
    await harness.click(USER, "Подтвердить")
    order = await orders.get_order(1)
    assert (order.method, order.table_no, order.payment_method) == (OrderMethod.TABLE, 5, PaymentMethod.ON_SITE)
    assert "стол №5" in harness.session.last_message(STAFF)["text"]


async def test_double_confirm_creates_one_order(harness, always_open):
    import asyncio

    await add_pizza(qty=1)
    await open_checkout(harness, start="/start table_2")
    await harness.click(USER, "Без комментария")
    confirm_screen = harness.screen(USER)
    await asyncio.gather(
        harness.click(USER, "Подтвердить", message=confirm_screen),
        harness.click(USER, "Подтвердить", message=confirm_screen),
    )
    assert len(await orders.get_user_orders(USER)) == 1


async def test_item_stopped_during_checkout(harness, always_open):
    pizza = await add_pizza(qty=1)
    await open_checkout(harness, start="/start table_2")
    await harness.click(USER, "Без комментария")
    await menu.toggle_availability(pizza.id)
    await harness.click(USER, "Подтвердить")
    assert "закончилось: Маргарита" in harness.screen_text(USER)
    assert await orders.get_user_orders(USER) == []


async def test_sticker_during_checkout_keeps_flow(harness, always_open):
    await add_pizza()
    await open_checkout(harness)
    await harness.send(USER, None, sticker={"file_id": "s", "file_unique_id": "s", "type": "regular",
                                             "width": 1, "height": 1, "is_animated": False, "is_video": False})
    assert "выберите вариант кнопкой" in harness.screen_text(USER)
    assert "Как хотите получить заказ" in harness.screen_text(USER)


async def test_staff_chat_failure_does_not_break_order(harness, always_open, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", (777,))
    harness.session.blocked_chats.add(STAFF)
    await add_pizza(qty=1)
    await open_checkout(harness, start="/start table_1")
    await harness.click(USER, "Без комментария")
    await harness.click(USER, "Подтвердить")
    assert "оформлен" in harness.screen_text(USER)
    alerts = [m for m in harness.session.calls(SendMessage) if m.chat_id == 777]
    assert alerts and "не удалось отправить" in alerts[0].text


async def test_leaving_checkout_via_menu_resets_input(harness, always_open):
    await add_pizza()
    await open_checkout(harness)
    await harness.click(USER, "Доставка")
    await harness.click(USER, "Зона 1")          # бот ждёт адрес
    from keyboards.callbacks import Nav

    # кнопка «Меню» со старого сообщения (без /start)
    await harness.click_data(USER, Nav(to="menu").pack(), harness.screen(USER))
    await harness.send(USER, "просто текст")     # это уже не адрес
    assert "Я понимаю кнопки" in harness.screen_text(USER)
