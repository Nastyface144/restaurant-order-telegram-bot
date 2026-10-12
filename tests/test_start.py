from datetime import time

import config
from database import users

USER = 1001


async def test_start_shows_main_menu(harness, always_open):
    await harness.send(USER, "/start")
    text = harness.screen_text(USER)
    assert "Пицца у дома" in text and "🟢 Открыто" in text
    assert harness.buttons(USER) == [
        "📖 Меню", "🛒 Корзина", "📦 Мои заказы", "📅 Забронировать столик", "📍 Контакты",
    ]
    assert await users.get_user(USER) is not None


async def test_single_message_navigation(harness, always_open):
    await harness.send(USER, "/start")
    first_id = harness.screen(USER)["message_id"]
    await harness.click(USER, "Контакты")
    assert harness.screen(USER)["message_id"] == first_id  # отредактировано, а не новое
    assert "Часы работы" in harness.screen_text(USER)
    await harness.click(USER, "Главное меню")
    assert harness.screen(USER)["message_id"] == first_id
    assert len(harness.session.chat_messages(USER)) == 1

    await harness.send(USER, "/start")  # новый /start — новый экран, старый удалён
    assert len(harness.session.chat_messages(USER)) == 1


async def test_disabled_sections_are_hidden(harness, always_open, monkeypatch):
    monkeypatch.setattr(config, "FEATURES", config.Features(booking=False))
    await harness.send(USER, "/start")
    assert "📅 Забронировать столик" not in harness.buttons(USER)


async def test_table_deep_link(harness, always_open):
    await harness.send(USER, "/start table_7")
    assert "столом <b>№7</b>" in harness.screen_text(USER)
    assert "🚪 Я уже не за столом" in harness.buttons(USER)
    await harness.click(USER, "Я уже не за столом")
    assert "№7" not in harness.screen_text(USER)


async def test_bad_table_number(harness, always_open):
    await harness.send(USER, f"/start table_{config.TABLES_COUNT + 1}")
    assert "Не удалось распознать номер стола" in harness.screen_text(USER)
    assert (await users.get_user(USER)).table_no is None


async def test_closed_venue_offers_preorder(harness, monkeypatch):
    monkeypatch.setattr(config, "WORKING_HOURS", {d: None for d in range(7)} | {0: (time(10), time(10, 1))})
    await harness.send(USER, "/start")
    text = harness.screen_text(USER)
    assert "Сейчас закрыто" in text or "Скоро закрываемся" in text
    assert "заранее" in text


async def test_unknown_text_and_stale_button(harness, always_open):
    await harness.send(USER, "привет")
    assert "Я понимаю кнопки" in harness.screen_text(USER)
    await harness.click_data(USER, "zzz:1", harness.screen(USER))
    answer = harness.session.requests[-1]
    assert "устарела" in answer.text
