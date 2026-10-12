from datetime import timedelta

from database import bookings, cart, demo_data, menu, orders, users
from database.models import BookingStatus, OrderItem, OrderMethod, OrderStatus, PaymentMethod
from utils.timeutil import now_local


def to_order_items(lines):
    return [
        OrderItem(
            item_id=l.item.id, title=l.item.title, size_code=l.size_code,
            size_title=l.size.title if l.size else "", addon_codes=l.addon_codes,
            addons_title=", ".join(a.title for a in l.addons), unit_price=l.unit_price, qty=l.qty,
        )
        for l in lines
    ]


async def first_pizza():
    category = (await menu.get_categories())[0]
    return (await menu.get_items(category.id))[0]


async def test_demo_menu(database):
    assert not await demo_data.seed_if_empty()  # повторно не заливается
    categories = await menu.get_categories()
    assert [c.title for c in categories] == ["Пицца", "Закуски", "Напитки", "Десерты"]
    count = 0
    for c in categories:
        count += len(await menu.get_items(c.id))
    assert count == 12


async def test_item_prices(database):
    pizza = await first_pizza()
    assert [s.code for s in pizza.sizes] == ["25", "30", "35"]
    assert pizza.default_size.code == "30"
    assert pizza.unit_price("30", ["cheese", "bacon", "unknown"]) == 640 + 90 + 110
    assert pizza.unit_price("nope", []) == 0 + pizza.price
    assert pizza.min_price == 490


async def test_cart_merges_same_lines_and_changes_qty(database):
    pizza = await first_pizza()
    await users.upsert_user(1, "Иван", None)
    await cart.add_to_cart(1, pizza.id, "30", ["cheese", "bacon"])
    await cart.add_to_cart(1, pizza.id, "30", ["bacon", "cheese"], qty=2)
    await cart.add_to_cart(1, pizza.id, "25", [])
    lines = await cart.get_cart(1)
    assert [(l.size_code, l.qty) for l in lines] == [("30", 3), ("25", 1)]
    assert await cart.count_cart_items(1) == 4

    await cart.change_qty(1, lines[0].id, -1)
    await cart.change_qty(1, lines[1].id, -1)  # 1 → 0: позиция удаляется
    lines = await cart.get_cart(1)
    assert [(l.size_code, l.qty) for l in lines] == [("30", 2)]

    await cart.change_qty(1, lines[0].id, +1000)
    assert (await cart.get_cart(1))[0].qty == cart.MAX_QTY

    # чужую корзину менять нельзя
    await cart.remove_line(2, lines[0].id)
    assert len(await cart.get_cart(1)) == 1


async def test_stop_list(database):
    pizza = await first_pizza()
    assert await menu.toggle_availability(pizza.id) is False
    assert await menu.count_stopped() == 1
    category = (await menu.get_categories())[0]
    assert pizza.id not in [i.id for i in await menu.get_items(category.id)]
    assert await menu.toggle_availability(pizza.id) is True


async def test_order_lifecycle(database):
    pizza = await first_pizza()
    await users.upsert_user(1, "Иван", None)
    await cart.add_to_cart(1, pizza.id, "30", ["cheese"], qty=2)
    items = to_order_items(await cart.get_cart(1))
    order_id = await orders.create_order(
        user_id=1, status=OrderStatus.NEW, method=OrderMethod.DELIVERY, customer_name="Иван",
        phone="+79990000000", payment_method=PaymentMethod.CASH, items=items,
        delivery_fee=150, zone_id=1, address="Садовая, 1",
    )
    order = await orders.get_order(order_id)
    assert order.subtotal == (640 + 90) * 2
    assert order.total == order.subtotal + 150
    assert order.items[0].full_title == "Маргарита, 30 см + Двойной сыр"
    assert await cart.get_cart(1) == []

    assert await orders.update_status(order_id, OrderStatus.ACCEPTED, expected=[OrderStatus.NEW])
    # повторное нажатие той же кнопки ничего не меняет
    assert not await orders.update_status(order_id, OrderStatus.ACCEPTED, expected=[OrderStatus.NEW])

    today = now_local().date()
    assert [o.id for o in await orders.get_orders_for_day(today)] == [order_id]
    assert [o.id for o in await orders.get_user_orders(1)] == [order_id]


async def test_pending_payment_hidden_until_paid(database):
    pizza = await first_pizza()
    await cart.add_to_cart(1, pizza.id, "25", [])
    items = to_order_items(await cart.get_cart(1))
    order_id = await orders.create_order(
        user_id=1, status=OrderStatus.PENDING_PAYMENT, method=OrderMethod.PICKUP, customer_name="Иван",
        phone=None, payment_method=PaymentMethod.ONLINE, items=items, clear_cart=False,
    )
    assert await orders.get_user_orders(1) == []
    assert await orders.mark_paid(order_id, "tg", "prov")
    assert not await orders.mark_paid(order_id, "tg", "prov")
    order = await orders.get_order(order_id)
    assert order.is_paid and order.status == OrderStatus.NEW


async def test_bookings(database):
    starts = now_local().replace(second=0, microsecond=0) + timedelta(days=1)
    booking_id = await bookings.create_booking(user_id=1, starts_at=starts, guests=4, name="Анна", phone="+7")
    await bookings.set_admin_messages(booking_id, [(10, 20), (11, 21)])
    booking = await bookings.get_booking(booking_id)
    assert booking.starts_at == starts
    assert booking.admin_messages == ((10, 20), (11, 21))
    assert await bookings.update_status(booking_id, BookingStatus.CONFIRMED, expected=BookingStatus.PENDING)
    assert not await bookings.update_status(booking_id, BookingStatus.REJECTED, expected=BookingStatus.PENDING)
    assert [b.id for b in await bookings.get_bookings_for_day(starts.date())] == [booking_id]


async def test_users(database):
    await users.upsert_user(1, "Иван", "ivan")
    await users.mark_blocked(1)
    assert await users.get_active_user_ids() == []
    await users.upsert_user(1, "Иван Петров", "ivan")  # снова написал боту
    assert await users.get_active_user_ids() == [1]
    await users.save_contact_details(1, phone="+7999")
    await users.save_contact_details(1, address="Садовая, 1", zone_id=2)
    user = await users.get_user(1)
    assert (user.full_name, user.phone, user.last_address, user.last_zone_id) == ("Иван Петров", "+7999", "Садовая, 1", 2)
