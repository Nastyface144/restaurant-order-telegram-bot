import pytest

import config
from database import cart, menu, orders
from tests.test_checkout import STAFF, USER
from tests.test_staff import place_order


@pytest.fixture(autouse=True)
def staff_chat(monkeypatch):
    monkeypatch.setattr(config, "STAFF_CHAT_ID", STAFF)


async def test_empty_history(harness, always_open):
    await harness.send(USER, "/start")
    await harness.click(USER, "Мои заказы")
    assert "ещё ничего не заказывали" in harness.screen_text(USER)
    assert "📖 Открыть меню" in harness.buttons(USER)


async def test_history_details_and_repeat(harness, always_open):
    await place_order(harness)  # 2 × Маргарита 30 см
    await harness.click(USER, "Мои заказы")
    assert harness.buttons(USER)[0].startswith("№1 · ") and "Новый" in harness.buttons(USER)[0]

    await harness.click(USER, "№1")
    text = harness.screen_text(USER)
    assert "Заказ №1" in text and "Маргарита, 30 см × 2" in text and "ул. Садовая, 5" in text

    await harness.click(USER, "Повторить заказ")
    assert "Добавили в корзину 2 позиции из заказа №1" in harness.screen_text(USER)
    lines = await cart.get_cart(USER)
    assert [(line.item.title, line.size_code, line.qty) for line in lines] == [("Маргарита", "30", 2)]
    assert len(harness.session.chat_messages(USER)) == 1


async def test_repeat_with_stopped_item(harness, always_open):
    await place_order(harness)
    item = (await menu.get_items((await menu.get_categories())[0].id))[0]
    await menu.toggle_availability(item.id)
    await harness.click(USER, "Мои заказы")
    await harness.click(USER, "№1")
    await harness.click(USER, "Повторить заказ")
    assert "Повторить не получилось" in harness.screen_text(USER)
    assert await cart.get_cart(USER) == []


async def test_status_notification_opens_order(harness, always_open):
    await place_order(harness)
    await harness.click(STAFF, "Принять", user_id=9001)
    notification = harness.session.last_message(USER)
    assert "принят" in notification["text"]
    await harness.click(USER, "Открыть заказ", message=notification)
    assert "Статус: <b>✅ Принят</b>" in harness.screen_text(USER)


async def test_cannot_open_foreign_order(harness, always_open):
    await place_order(harness)
    from keyboards.callbacks import OrdersCb

    other = 5555
    await harness.send(other, "/start")
    await harness.click_data(other, OrdersCb(a="view", id=1).pack(), harness.screen(other))
    from aiogram.methods import AnswerCallbackQuery
    assert harness.session.calls(AnswerCallbackQuery)[-1].text == "Заказ не найден"
    assert (await orders.get_order(1)).user_id == USER
