import pytest
from aiogram.methods import AnswerPreCheckoutQuery, SendInvoice

import config
from database import cart, orders
from database.models import OrderStatus
from tests.test_checkout import STAFF, USER, add_pizza, open_checkout


@pytest.fixture(autouse=True)
def online(monkeypatch):
    monkeypatch.setattr(config, "STAFF_CHAT_ID", STAFF)
    monkeypatch.setattr(config, "PAYMENT_TOKEN", "381764678:TEST:100500")
    monkeypatch.setattr(config, "FEATURES", config.Features(online_payment=True))


async def checkout_online(h):
    await add_pizza(qty=1)  # 640
    await open_checkout(h)
    await h.click(USER, "Самовывоз")
    await h.click(USER, "Через 30 мин")
    await h.send(USER, "+79990000000")
    await h.click(USER, "Без комментария")
    await h.click(USER, "Онлайн-оплата")
    assert "Перейти к оплате · 640" in " ".join(h.buttons(USER))
    await h.click(USER, "Перейти к оплате")


async def pre_checkout(h, amount, payload="order:1", user_id=USER):
    await h.feed({"pre_checkout_query": {
        "id": "pcq", "from": h.user(user_id), "currency": "RUB",
        "total_amount": amount, "invoice_payload": payload,
    }})
    return h.session.calls(AnswerPreCheckoutQuery)[-1]


async def pay(h, amount=64000, payload="order:1"):
    await h.send(USER, None, successful_payment={
        "currency": "RUB", "total_amount": amount, "invoice_payload": payload,
        "telegram_payment_charge_id": "tg_1", "provider_payment_charge_id": "yk_1",
    })


async def test_invoice_sent_and_order_waits_for_payment(harness, always_open):
    await checkout_online(harness)
    invoice = harness.session.calls(SendInvoice)[-1]
    assert invoice.payload == "order:1" and invoice.currency == "RUB"
    assert sum(p.amount for p in invoice.prices) == 64000
    assert "тестовой картой" in invoice.description
    # экран заменён счётом — в чате одно сообщение
    assert len(harness.session.chat_messages(USER)) == 1
    assert "invoice" in harness.screen(USER)

    order = await orders.get_order(1)
    assert order.status == OrderStatus.PENDING_PAYMENT
    assert await cart.get_cart(USER)  # корзина сохраняется до оплаты
    assert not harness.session.chat_messages(STAFF)  # персонал ещё не видит заказ


async def test_successful_payment(harness, always_open):
    await checkout_online(harness)
    answer = await pre_checkout(harness, 64000)
    assert answer.ok
    await pay(harness)

    order = await orders.get_order(1)
    assert order.is_paid and order.status == OrderStatus.NEW
    assert await cart.get_cart(USER) == []
    assert "✅ оплачен" in harness.session.last_message(STAFF)["text"]
    assert "Заказ №1 оформлен" in harness.screen_text(USER)
    assert len(harness.session.chat_messages(USER)) == 1  # счёт заменён экраном «оформлен»

    # повторное уведомление о том же платеже не дублирует заказ у персонала
    await pay(harness)
    assert len(harness.session.chat_messages(STAFF)) == 1


async def test_pre_checkout_rejects_wrong_amount_and_foreign_order(harness, always_open):
    await checkout_online(harness)
    assert not (await pre_checkout(harness, 100)).ok
    assert not (await pre_checkout(harness, 64000, user_id=999)).ok
    assert not (await pre_checkout(harness, 64000, payload="order:777")).ok
    assert not (await pre_checkout(harness, 64000, payload="garbage")).ok


async def test_cancel_invoice_keeps_cart(harness, always_open):
    await checkout_online(harness)
    await harness.click(USER, "Отменить")
    assert "Оплата отменена" in harness.screen_text(USER)
    assert (await orders.get_order(1)).status == OrderStatus.CANCELLED
    assert await cart.get_cart(USER)
    assert not (await pre_checkout(harness, 64000)).ok  # оплатить отменённый заказ нельзя


async def test_payment_after_timeout_cancel_still_counts(harness, always_open):
    await checkout_online(harness)
    await orders.update_status(1, OrderStatus.CANCELLED, expected=[OrderStatus.PENDING_PAYMENT])
    await pay(harness)  # деньги уже списаны — заказ оживает
    assert (await orders.get_order(1)).status == OrderStatus.NEW


async def test_payment_arrives_during_new_checkout(harness, always_open):
    await checkout_online(harness)
    await add_pizza(qty=1)
    await harness.send(USER, "/start")
    await harness.click(USER, "Корзина")
    await harness.click(USER, "Оформить заказ")  # клиент в состоянии оформления
    await pay(harness)
    assert (await orders.get_order(1)).is_paid
