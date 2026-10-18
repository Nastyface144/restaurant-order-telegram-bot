import asyncio

import pytest
from aiogram.methods import CopyMessage

import admin.broadcast
import config
from database import menu, users
from tests.test_checkout import STAFF, USER
from tests.test_staff import place_order

ADMIN = 8008


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", (ADMIN,))
    monkeypatch.setattr(config, "STAFF_CHAT_ID", STAFF)
    monkeypatch.setattr(admin.broadcast, "SEND_INTERVAL", 0)


async def test_admin_only_for_admins(harness, always_open):
    await harness.send(USER, "/admin")
    assert "Админ-панель" not in harness.screen_text(USER)


async def test_dashboard_with_stats(harness, always_open):
    await place_order(harness)              # 1479 ₽, выполним
    for button in ["Принять", "Готовится", "Курьер выехал", "Доставлен"]:
        await harness.click(STAFF, button, user_id=1)
    await place_order(harness)              # 1479 ₽, в работе
    await place_order(harness)              # отклоним
    await harness.click(STAFF, "Отклонить", user_id=1)
    await harness.click(STAFF, config.REJECT_REASONS[0], user_id=1)

    await harness.send(ADMIN, "/admin")
    text = harness.screen_text(ADMIN)
    assert "Заказов: <b>3</b>" in text
    assert "в работе 1 · выполнено 1 · отклонено 1" in text
    assert "Выручка: <b>1 479 ₽</b>" in text
    assert "ещё в работе на 1 479 ₽" in text

    await harness.click(ADMIN, "Заказы сегодня")
    text = harness.screen_text(ADMIN)
    assert "<b>№3</b>" in text and "❌ Отклонён" in text and "🎉 Доставлен" in text
    await harness.click(ADMIN, "Назад")
    await harness.click(ADMIN, "Брони сегодня")
    assert "Броней нет" in harness.screen_text(ADMIN)
    assert len(harness.session.chat_messages(ADMIN)) == 1


async def test_stop_list_toggle(harness, always_open):
    await harness.send(ADMIN, "/admin")
    await harness.click(ADMIN, "Стоп-лист")
    await harness.click(ADMIN, "Пицца")
    assert "✅ Маргарита" in harness.buttons(ADMIN)
    await harness.click(ADMIN, "✅ Маргарита")
    assert "🚫 Маргарита" in harness.buttons(ADMIN)
    item = (await menu.get_items((await menu.get_categories())[0].id, only_available=False))[0]
    assert not item.is_available
    await harness.click(ADMIN, "Назад")
    assert "🍕 Пицца · 🚫 1" in harness.buttons(ADMIN)

    # клиент блюдо не видит
    await harness.send(USER, "/start")
    await harness.click(USER, "меню")
    await harness.click(USER, "Пицца")
    assert not any("Маргарита" in b for b in harness.buttons(USER))

    await harness.click(ADMIN, "Пицца")
    await harness.click(ADMIN, "🚫 Маргарита")
    assert (await menu.get_item(item.id)).is_available


async def test_broadcast(harness, always_open):
    for uid in (101, 102, 103):
        await harness.send(uid, "/start")
    harness.session.blocked_chats.add(103)

    await harness.send(ADMIN, "/admin")
    await harness.click(ADMIN, "Рассылка")
    await harness.send(ADMIN, None, sticker={"file_id": "s", "file_unique_id": "s", "type": "regular",
                                              "width": 1, "height": 1, "is_animated": False, "is_video": False})
    assert "только текст или фото" in harness.screen_text(ADMIN)
    await harness.send(ADMIN, "🔥 Сегодня -20% на пиццу!")
    assert "получат <b>3</b> клиента" in harness.screen_text(ADMIN)
    await harness.click(ADMIN, "Отправить")

    from admin.handlers import _running_broadcasts
    await asyncio.gather(*_running_broadcasts)

    copies = harness.session.calls(CopyMessage)
    assert sorted(c.chat_id for c in copies) == [101, 102, 103]
    text = harness.screen_text(ADMIN)
    assert "Рассылка завершена" in text and "Доставлено: 2 из 3" in text and "Заблокировали бота: 1" in text
    assert (await users.get_user(103)).is_blocked

    # повторный /start снимает пометку «заблокировал»
    harness.session.blocked_chats.discard(103)
    await harness.send(103, "/start")
    assert not (await users.get_user(103)).is_blocked


async def test_broadcast_photo_and_cancel(harness, always_open):
    await harness.send(ADMIN, "/admin")
    await harness.click(ADMIN, "Рассылка")
    await harness.click(ADMIN, "Отмена")
    assert "Админ-панель" in harness.screen_text(ADMIN)

    await harness.click(ADMIN, "Рассылка")
    await harness.send(ADMIN, None, photo=[{"file_id": "p", "file_unique_id": "p", "width": 1, "height": 1}],
                       caption="Новое меню!")
    assert "Отправляем?" in harness.screen_text(ADMIN)


async def test_start_during_broadcast_input_is_not_broadcast(harness, always_open):
    await harness.send(ADMIN, "/admin")
    await harness.click(ADMIN, "Рассылка")
    await harness.send(ADMIN, "/start")
    assert "Пицца у дома" in harness.screen_text(ADMIN)
