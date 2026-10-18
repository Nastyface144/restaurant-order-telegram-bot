from database import cart, menu

USER = 2002


async def open_menu(h):
    await h.send(USER, "/start")
    await h.click(USER, "меню")


async def test_categories_and_items(harness, always_open):
    await open_menu(harness)
    assert harness.buttons(USER)[:4] == ["🍕 Пицца", "🍟 Закуски", "🥤 Напитки", "🍰 Десерты"]
    await harness.click(USER, "Пицца")
    buttons = harness.buttons(USER)
    assert "Маргарита · от 490 ₽" in buttons
    assert buttons[-2:] == ["← Назад", "🛒"]
    assert "<b>Маргарита</b> · от 490" in harness.screen_text(USER)  # подпись — как строчки меню


async def test_item_card_options_and_add(harness, always_open):
    await open_menu(harness)
    await harness.click(USER, "Пицца")
    await harness.click(USER, "Пепперони")
    card = harness.screen(USER)
    assert "photo" in card
    assert "Пепперони" in card["caption"] and "30 см" in card["caption"]
    # file_id фото закэшировался после первой отправки
    item = (await menu.get_items((await menu.get_categories())[0].id))[1]
    assert item.photo_file_id

    await harness.click(USER, "35 см")
    await harness.click(USER, "Бекон")
    await harness.click(USER, "+", exact=True)
    card = harness.screen(USER)
    assert card["message_id"] == harness.session.chat_messages(USER)[0]["message_id"]
    assert "✓ 35 см · 890 ₽" in harness.buttons(USER)
    assert "✓ Бекон 110 ₽" in harness.buttons(USER)
    assert "💰 <b>2 000 ₽</b> · 2 × 1 000 ₽ · 35 см + бекон" in card["caption"]

    await harness.click(USER, "В корзину · 2 000")
    lines = await cart.get_cart(USER)
    summary = [(line.item.title, line.size_code, line.addon_codes, line.qty) for line in lines]
    assert summary == [("Пепперони", "35", ("bacon",), 2)]
    # после добавления количество сброшено, счётчик корзины обновился
    assert "1 шт" in harness.buttons(USER)
    assert "🛒 2 000 ₽" in harness.buttons(USER)

    await harness.click(USER, "Назад")
    assert "Нажмите на блюдо" in harness.screen_text(USER)
    assert len(harness.session.chat_messages(USER)) == 1


async def test_stopped_item_hidden_and_unavailable(harness, always_open):
    await open_menu(harness)
    await harness.click(USER, "Пицца")
    category_screen = harness.screen(USER)
    item = (await menu.get_items((await menu.get_categories())[0].id))[0]
    await menu.toggle_availability(item.id)
    await harness.click(USER, "Маргарита", message=category_screen)  # кнопка со старого экрана
    from aiogram.methods import AnswerCallbackQuery
    assert "недоступно" in harness.session.calls(AnswerCallbackQuery)[-1].text
    assert "Что будем заказывать" in harness.screen_text(USER)
    assert "Маргарита" not in " ".join(harness.buttons(USER))


async def test_stale_file_id_is_reuploaded(harness, always_open):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import EditMessageMedia, SendPhoto

    item = (await menu.get_items((await menu.get_categories())[0].id))[0]
    await menu.save_photo_file_id(item.id, "BROKEN")
    original = harness.session.make_request

    async def flaky(bot, method, timeout=None):
        broken = (isinstance(method, SendPhoto) and method.photo == "BROKEN") or (
            isinstance(method, EditMessageMedia) and method.media.media == "BROKEN")
        if broken:
            raise TelegramBadRequest(method=method, message="Bad Request: wrong file identifier")
        return await original(bot, method, timeout)

    harness.session.make_request = flaky
    await open_menu(harness)
    await harness.click(USER, "Пицца")
    await harness.click(USER, "Маргарита")
    assert "photo" in harness.screen(USER)
    assert (await menu.get_item(item.id)).photo_file_id != "BROKEN"
