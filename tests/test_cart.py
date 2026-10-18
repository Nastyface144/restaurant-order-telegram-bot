from database import cart, menu

USER = 3003
NB = " "


async def fill_cart():
    categories = await menu.get_categories()
    pizza = (await menu.get_items(categories[0].id))[1]        # Пепперони
    drink = (await menu.get_items(categories[2].id))[1]        # Морс
    await cart.add_to_cart(USER, pizza.id, "30", ["bacon"], 2)  # (720 + 110) × 2 = 1660
    await cart.add_to_cart(USER, drink.id, "05", [])            # 190
    return pizza, drink


async def test_empty_cart(harness, always_open):
    await harness.send(USER, "/start")
    assert not any("Корзина" in b for b in harness.buttons(USER))  # пустая корзина не мешает на главной
    await harness.click(USER, "меню")
    await harness.click(USER, "🛒", exact=True)
    assert "Корзина пуста" in harness.screen_text(USER)


async def test_cart_totals_with_delivery(harness, always_open):
    await fill_cart()
    await harness.send(USER, "/start")
    assert f"🛒 Корзина · 3 шт · 1{NB}850{NB}₽" in harness.buttons(USER)  # сумма прямо на главной
    await harness.click(USER, "Корзина · 3")
    text = harness.screen_text(USER)
    assert f"<b>Пепперони</b> · 30 см + Бекон\n2 × 830{NB}₽ = <b>1{NB}660{NB}₽</b>" in text
    assert f"<b>Морс клюквенный</b> · 0,5 л\n190{NB}₽" in text
    assert f"Итого: <b>1{NB}850{NB}₽</b>" in text
    assert f"🛵 Доставка от 150{NB}₽" in text
    assert f"💡 Ещё 150{NB}₽ — и доставим бесплатно" in text
    assert f"✅ Оформить заказ · 1{NB}850{NB}₽" in harness.buttons(USER)


async def test_min_order_and_free_delivery(harness, always_open):
    categories = await menu.get_categories()
    fries = (await menu.get_items(categories[1].id))[0]
    await cart.add_to_cart(USER, fries.id, "", [], 4)  # 760: зона 1 ок, зоне 2 не хватает 440
    await harness.send(USER, "/start")
    await harness.click(USER, "Корзина")
    assert f"💡 Ещё 1{NB}240{NB}₽ — и доставим бесплатно" in harness.screen_text(USER)

    await cart.add_to_cart(USER, fries.id, "", [], 7)  # 2090 → в зоне 1 доставка бесплатна
    await harness.click(USER, "Добавить ещё")
    await harness.click(USER, "🛒")
    assert "🎁 Доставка бесплатно (зона 1)" in harness.screen_text(USER)


async def test_below_min_order_suggests_pickup(harness, always_open):
    categories = await menu.get_categories()
    drink = (await menu.get_items(categories[2].id))[1]
    await cart.add_to_cart(USER, drink.id, "05", [])  # 190 < 700
    await harness.send(USER, "/start")
    await harness.click(USER, "Корзина")
    text = harness.screen_text(USER)
    assert f"Доставка — от 700{NB}₽: добавьте ещё 510{NB}₽" in text and "Самовывоз — без минимальной суммы" in text


async def test_change_qty_delete_clear(harness, always_open):
    await fill_cart()
    await harness.send(USER, "/start")
    await harness.click(USER, "Корзина")
    await harness.click(USER, "−", exact=True)       # пепперони 2 → 1
    assert [line.qty for line in await cart.get_cart(USER)] == [1, 1]
    await harness.click(USER, "+", exact=True)
    await harness.click(USER, "+", exact=True)
    assert [line.qty for line in await cart.get_cart(USER)] == [3, 1]
    await harness.click(USER, "🗑", exact=True)       # у морса одна штука — вместо «минуса» корзина
    assert [line.item.title for line in await cart.get_cart(USER)] == ["Пепперони"]
    await harness.click(USER, "Очистить")
    await harness.click(USER, "Нет, оставить")
    assert len(await cart.get_cart(USER)) == 1
    await harness.click(USER, "Очистить")
    await harness.click(USER, "Да, очистить")
    assert await cart.get_cart(USER) == []
    assert "Корзина пуста" in harness.screen_text(USER)
    assert len(harness.session.chat_messages(USER)) == 1


async def test_stopped_item_in_cart(harness, always_open):
    pizza, _ = await fill_cart()
    await menu.toggle_availability(pizza.id)
    await harness.send(USER, "/start")
    await harness.click(USER, "Корзина")
    text = harness.screen_text(USER)
    assert "⛔ <s>Пепперони" in text
    assert f"Итого: <b>190{NB}₽</b>" in text


async def test_table_mode_totals(harness, always_open):
    await fill_cart()
    await harness.send(USER, "/start table_3")
    await harness.click(USER, "Корзина")
    text = harness.screen_text(USER)
    assert "Принесём к столу №3, оплата на месте" in text
    assert "Доставка" not in text
