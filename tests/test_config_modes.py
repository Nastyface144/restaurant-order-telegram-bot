"""Режимы из README «Примеры адаптации» действительно работают."""

import config
from database import orders
from database.models import OrderMethod
from tests.test_checkout import USER, add_pizza, open_checkout


async def test_delivery_only_skips_method_step(harness, always_open, monkeypatch):
    monkeypatch.setattr(config, "FEATURES", config.Features(pickup=False, table=False, booking=False))
    await add_pizza()
    await open_checkout(harness)
    assert "Выберите зону доставки" in harness.screen_text(USER)
    assert "шаг 1 из 7" in harness.screen_text(USER)
    await harness.click(USER, "Назад")
    assert "Корзина" in harness.screen_text(USER)


async def test_single_zone_skips_zone_step(harness, always_open, monkeypatch):
    monkeypatch.setattr(config, "DELIVERY_ZONES", config.DELIVERY_ZONES[:1])
    await add_pizza()
    await open_checkout(harness)
    await harness.click(USER, "Доставка")
    assert "Напишите адрес" in harness.screen_text(USER)
    await harness.send(USER, "ул. Садовая, 1")
    await harness.click(USER, "Как можно скорее")
    await harness.send(USER, "+79990000000")
    await harness.click(USER, "Без комментария")
    await harness.click(USER, "Наличными")
    await harness.click(USER, "Подтвердить")
    assert (await orders.get_order(1)).zone_id == config.DELIVERY_ZONES[0].id


async def test_coffee_shop_pickup_only(harness, always_open, monkeypatch):
    monkeypatch.setattr(config, "FEATURES", config.Features(delivery=False, booking=False, card_on_receipt=False))
    await add_pizza()
    await open_checkout(harness)
    # способ один, оплата одна (наличные) — сразу время, а шаг оплаты пропущен
    assert "Через 15 мин" in harness.buttons(USER)
    await harness.click(USER, "Через 15 мин")
    await harness.send(USER, "+79990000000")
    await harness.click(USER, "Без комментария")
    assert "Проверьте заказ" in harness.screen_text(USER)
    await harness.click(USER, "Подтвердить")
    assert (await orders.get_order(1)).method == OrderMethod.PICKUP


async def test_menu_only_without_ordering(harness, always_open, monkeypatch):
    monkeypatch.setattr(config, "FEATURES", config.Features(delivery=False, pickup=False, table=False))
    await harness.send(USER, "/start")
    assert "🛒 Корзина" not in harness.buttons(USER)
    await harness.click(USER, "Меню")
    await harness.click(USER, "Пицца")
    await harness.click(USER, "Маргарита")
    assert not any("Добавить" in b for b in harness.buttons(USER))
