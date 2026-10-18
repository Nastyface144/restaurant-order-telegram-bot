import asyncio

import pytest
from aiogram.methods import AnswerCallbackQuery, SendMessage

import config
from database import orders
from database.models import OrderStatus
from tests.test_checkout import STAFF, USER, add_pizza, open_checkout

COOK = 9001


@pytest.fixture(autouse=True)
def staff_chat(monkeypatch):
    monkeypatch.setattr(config, "STAFF_CHAT_ID", STAFF)


async def place_order(h, method="delivery"):
    await add_pizza()
    if method == "table":
        await open_checkout(h, start="/start table_4")
    else:
        await open_checkout(h)
        if method == "delivery":
            await h.click(USER, "Доставка")
            await h.click(USER, "Зона 1")
            await h.send(USER, "ул. Садовая, 5")
            await h.click(USER, "Как можно скорее")
        else:
            await h.click(USER, "Самовывоз")
            await h.click(USER, "Через 15 мин")
        await h.send(USER, "+79990000000")
    await h.click(USER, "Без комментария")
    if method != "table":
        await h.click(USER, "Наличными")
    await h.click(USER, "Подтвердить")


def client_messages(h) -> list[str]:
    return [m.text for m in h.session.calls(SendMessage) if m.chat_id == USER]


async def staff_click(h, text):
    await h.click(STAFF, text, user_id=COOK)


def staff_alert(h) -> str:
    return h.session.calls(AnswerCallbackQuery)[-1].text or ""


@pytest.mark.parametrize("method, chain, final_text", [
    ("delivery", ["Принять", "Готовится", "Курьер выехал", "Доставлен"], "доставлен"),
    ("pickup", ["Принять", "Готовится", "Готов к выдаче", "Выдан"], "выдан"),
    ("table", ["Принять", "Готовится", "Готов", "Подан"], "Приятного аппетита"),
])
async def test_status_chain(harness, always_open, method, chain, final_text):
    await place_order(harness, method)
    card_id = harness.session.last_message(STAFF)["message_id"]
    assert harness.buttons(STAFF) == ["✅ Принять", "❌ Отклонить"]

    for button in chain:
        await staff_click(harness, button)
        assert "Клиент уведомлён" in staff_alert(harness)

    order = await orders.get_order(1)
    assert order.status == OrderStatus.COMPLETED and order.is_paid
    # карточка одна и та же, обновлена, кнопок больше нет
    card = harness.session.last_message(STAFF)
    assert card["message_id"] == card_id
    assert "🎉" in card["text"] and harness.buttons(STAFF) == []
    assert card["text"].rstrip().endswith(f"{harness.user(COOK)['first_name']}, {order.updated_at:%H:%M}</i>")

    notes = client_messages(harness)
    assert any("принят" in t for t in notes)
    assert any("Готовим ваш заказ" in t for t in notes)
    assert final_text in notes[-1]


async def test_reject_with_reason(harness, always_open):
    await place_order(harness)
    await staff_click(harness, "Отклонить")
    assert config.REJECT_REASONS[0] in harness.buttons(STAFF)
    await staff_click(harness, "Назад")
    assert harness.buttons(STAFF) == ["✅ Принять", "❌ Отклонить"]

    await staff_click(harness, "Отклонить")
    await staff_click(harness, config.REJECT_REASONS[2])
    order = await orders.get_order(1)
    assert order.status == OrderStatus.REJECTED and order.reject_reason == config.REJECT_REASONS[2]
    assert f"Причина: {config.REJECT_REASONS[2]}" in client_messages(harness)[-1]
    card = harness.session.last_message(STAFF)["text"]
    assert "❌ Отклонён" in card and config.REJECT_REASONS[2] in card
    assert harness.buttons(STAFF) == []


async def test_cannot_reject_after_courier_left(harness, always_open):
    await place_order(harness)
    stale_card = harness.session.last_message(STAFF).copy()
    for button in ["Принять", "Готовится", "Курьер выехал"]:
        await staff_click(harness, button)
    await harness.click(STAFF, "Отклонить", user_id=COOK, message=stale_card)
    assert "нельзя отклонить" in staff_alert(harness)
    assert (await orders.get_order(1)).status == OrderStatus.ON_THE_WAY


async def test_double_click_by_two_cooks(harness, always_open):
    await place_order(harness)
    card = harness.session.last_message(STAFF).copy()
    await asyncio.gather(
        harness.click(STAFF, "Принять", user_id=COOK, message=card),
        harness.click(STAFF, "Принять", user_id=COOK + 1, message=card),
    )
    assert sum("принят" in t for t in client_messages(harness)) == 1
    assert "Статус уже изменён" in [c.text for c in harness.session.calls(AnswerCallbackQuery)]


async def test_buttons_work_only_in_staff_chat(harness, always_open):
    await place_order(harness)
    card = harness.session.last_message(STAFF)
    # та же кнопка, но нажата в личке (например, переслали сообщение) — игнорируется
    fake = {**card, "chat": {"id": USER, "type": "private", "first_name": "x"}}
    await harness.click(USER, "Принять", message=fake)
    assert (await orders.get_order(1)).status == OrderStatus.NEW


async def test_client_blocked_bot(harness, always_open):
    from database import users

    await place_order(harness)
    harness.session.blocked_chats.add(USER)
    await staff_click(harness, "Принять")
    assert staff_alert(harness) == "Статус изменён"
    assert (await users.get_user(USER)).is_blocked
