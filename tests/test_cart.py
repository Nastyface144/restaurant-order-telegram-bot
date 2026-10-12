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
    await harness.click(USER, "Корзина")
    assert "Корзина пуста" in harness.screen_text(USER)


async def test_cart_totals_with_delivery(harness, always_open):
    await fill_cart()
    await harness.send(USER, "/start")
    await harness.click(USER, "Корзина · 3")
    text = harness.screen_text(USER)
    assert f"Пепперони, 30 см + Бекон\n    830{NB}₽ × 2 = 1{NB}660{NB}₽" in text
    assert f"Морс клюквенный, 0,5 л — 190{NB}₽" in text
    assert f"Товары: <b>1{NB}850{NB}₽</b>" in text
    assert f"Зона 1 — до 3 км: <b>2{NB}000{NB}₽</b> (доставка 150{NB}₽)" in text
    assert f"Зона 2 — 3–7 км: <b>2{NB}140{NB}₽</b> (доставка 290{NB}₽)" in text
    assert f"Самовывоз: <b>1{NB}850{NB}₽</b>" in text
    assert f"✅ Оформить заказ · 1{NB}850{NB}₽" in harness.buttons(USER)


async def test_min_order_and_free_delivery(harness, always_open):
    categories = await menu.get_categories()
    fries = (await menu.get_items(categories[1].id))[0]
    await cart.add_to_cart(USER, fries.id, "", [], 4)  # 760: зона 1 ок, зоне 2 не хватает 440
    await harness.send(USER, "/start")
    await harness.click(USER, "Корзина")
    assert f"заказ от 1{NB}200{NB}₽ — добавьте ещё 440{NB}₽" in harness.screen_text(USER)

    await cart.add_to_cart(USER, fries.id, "", [], 7)  # 2090 → в зоне 1 доставка бесплатна
    await harness.click(USER, "Меню")
    await harness.click(USER, "Корзина")
    assert f"<b>2{NB}090{NB}₽</b> (доставка бесплатно)" in harness.screen_text(USER)


async def test_change_qty_delete_clear(harness, always_open):
    await fill_cart()
    await harness.send(USER, "/start")
    await harness.click(USER, "Корзина")
    await harness.click(USER, "➖", exact=True)       # пепперони 2 → 1
    assert [line.qty for line in await cart.get_cart(USER)] == [1, 1]
    await harness.click(USER, "➕", exact=True)
    await harness.click(USER, "➕", exact=True)
    assert [line.qty for line in await cart.get_cart(USER)] == [3, 1]
    await harness.click(USER, "🗑", exact=True)       # удалить первую позицию
    assert [line.item.title for line in await cart.get_cart(USER)] == ["Морс клюквенный"]
    await harness.click(USER, "Очистить корзину")
    await harness.click(USER, "Нет, назад")
    assert len(await cart.get_cart(USER)) == 1
    await harness.click(USER, "Очистить корзину")
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
    assert f"Товары: <b>190{NB}₽</b>" in text


async def test_table_mode_totals(harness, always_open):
    await fill_cart()
    await harness.send(USER, "/start table_3")
    await harness.click(USER, "Корзина")
    text = harness.screen_text(USER)
    assert "Оплата на месте, за столом №3" in text
    assert "Итого с доставкой" not in text
