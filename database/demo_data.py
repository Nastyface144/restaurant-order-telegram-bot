"""Демо-меню вымышленной пиццерии «Пицца у дома».

Загружается в пустую базу при первом запуске. Чтобы заменить меню на своё,
отредактируйте этот файл и удалите data/bot.db (или правьте таблицы напрямую).

Поле photo: путь к файлу в assets/, URL картинки или Telegram file_id.
"""

from __future__ import annotations

import json
import logging

from .core import db

logger = logging.getLogger(__name__)

PIZZA_SIZES = [
    {"code": "25", "title": "25 см"},
    {"code": "30", "title": "30 см"},
    {"code": "35", "title": "35 см"},
]

PIZZA_ADDONS = [
    {"code": "cheese", "title": "Двойной сыр", "price": 90},
    {"code": "jalapeno", "title": "Халапеньо", "price": 50},
    {"code": "bacon", "title": "Бекон", "price": 110},
    {"code": "mushrooms", "title": "Шампиньоны", "price": 60},
]


def _pizza_sizes(p25: int, p30: int, p35: int) -> list[dict]:
    return [dict(size, price=price) for size, price in zip(PIZZA_SIZES, (p25, p30, p35), strict=True)]


CATEGORIES = [
    {
        "title": "Пицца",
        "emoji": "🍕",
        "items": [
            {
                "title": "Маргарита",
                "description": "Томатный соус, моцарелла, свежие томаты и базилик. Классика, с которой всё началось.",
                "photo": "assets/menu/margherita.jpg",
                "sizes": _pizza_sizes(490, 640, 790),
                "addons": PIZZA_ADDONS,
            },
            {
                "title": "Пепперони",
                "description": "Острая колбаса пепперони, моцарелла и фирменный томатный соус.",
                "photo": "assets/menu/pepperoni.jpg",
                "sizes": _pizza_sizes(560, 720, 890),
                "addons": PIZZA_ADDONS,
            },
            {
                "title": "Четыре сыра",
                "description": "Моцарелла, горгонзола, пармезан и чеддер на сливочном соусе.",
                "photo": "assets/menu/four_cheese.jpg",
                "sizes": _pizza_sizes(620, 790, 960),
                "addons": [a for a in PIZZA_ADDONS if a["code"] != "cheese"],
            },
            {
                "title": "Барбекю",
                "description": "Курица, бекон, красный лук и соус барбекю. Сытно и с дымком.",
                "photo": "assets/menu/bbq.jpg",
                "sizes": _pizza_sizes(610, 780, 940),
                "addons": PIZZA_ADDONS,
            },
        ],
    },
    {
        "title": "Закуски",
        "emoji": "🍟",
        "items": [
            {
                "title": "Картофель фри",
                "description": "Хрустящий картофель с морской солью. 150 г.",
                "photo": "assets/menu/fries.jpg",
                "price": 190,
                "addons": [
                    {"code": "cheese_sauce", "title": "Сырный соус", "price": 50},
                    {"code": "bbq_sauce", "title": "Соус барбекю", "price": 50},
                ],
            },
            {
                "title": "Куриные крылья",
                "description": "Запечённые крылья в медово-горчичной глазури. 6 шт.",
                "photo": "assets/menu/wings.jpg",
                "price": 390,
                "addons": [
                    {"code": "blue_cheese", "title": "Соус блю-чиз", "price": 60},
                ],
            },
            {
                "title": "Чесночный хлеб",
                "description": "Тёплая чиабатта с чесночным маслом и зеленью.",
                "photo": "assets/menu/garlic_bread.jpg",
                "price": 220,
                "addons": [
                    {"code": "mozzarella", "title": "С моцареллой", "price": 70},
                ],
            },
        ],
    },
    {
        "title": "Напитки",
        "emoji": "🥤",
        "items": [
            {
                "title": "Лимонад домашний",
                "description": "Лимон, мята и немного тростникового сахара.",
                "photo": "assets/menu/lemonade.jpg",
                "sizes": [
                    {"code": "03", "title": "0,3 л", "price": 160},
                    {"code": "05", "title": "0,5 л", "price": 220},
                ],
            },
            {
                "title": "Морс клюквенный",
                "description": "Из северной клюквы, без консервантов.",
                "photo": "assets/menu/mors.jpg",
                "sizes": [
                    {"code": "03", "title": "0,3 л", "price": 140},
                    {"code": "05", "title": "0,5 л", "price": 190},
                ],
            },
            {
                "title": "Капучино",
                "description": "Двойной эспрессо и молочная пена.",
                "photo": "assets/menu/cappuccino.jpg",
                "sizes": [
                    {"code": "s", "title": "250 мл", "price": 170},
                    {"code": "l", "title": "350 мл", "price": 220},
                ],
                "addons": [
                    {"code": "syrup", "title": "Сироп", "price": 40},
                    {"code": "oat", "title": "Овсяное молоко", "price": 60},
                ],
            },
        ],
    },
    {
        "title": "Десерты",
        "emoji": "🍰",
        "items": [
            {
                "title": "Чизкейк Нью-Йорк",
                "description": "Нежный сливочный чизкейк на песочной основе.",
                "photo": "assets/menu/cheesecake.jpg",
                "price": 290,
                "addons": [
                    {"code": "berry", "title": "Ягодный соус", "price": 40},
                ],
            },
            {
                "title": "Тирамису",
                "description": "Савоярди, маскарпоне, эспрессо и какао.",
                "photo": "assets/menu/tiramisu.jpg",
                "price": 320,
            },
        ],
    },
]


async def seed_if_empty() -> bool:
    """Заполняет меню демо-данными, если в базе ещё нет блюд. Возвращает True, если заполнило."""
    if await db.fetchval("SELECT EXISTS (SELECT 1 FROM items)"):
        return False

    async with db.transaction() as conn:
        for cat_sort, category in enumerate(CATEGORIES):
            cursor = await conn.execute(
                "INSERT INTO categories (title, emoji, sort) VALUES (?, ?, ?)",
                (category["title"], category["emoji"], cat_sort),
            )
            category_id = cursor.lastrowid
            for item_sort, item in enumerate(category["items"]):
                await conn.execute(
                    """
                    INSERT INTO items (category_id, title, description, price, photo, sizes, addons, sort)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        category_id,
                        item["title"],
                        item["description"],
                        item.get("price", 0),
                        item.get("photo"),
                        json.dumps(item.get("sizes", []), ensure_ascii=False),
                        json.dumps(item.get("addons", []), ensure_ascii=False),
                        item_sort,
                    ),
                )
    total = sum(len(c["items"]) for c in CATEGORIES)
    logger.info("Загружено демо-меню: %d категорий, %d блюд", len(CATEGORIES), total)
    return True
