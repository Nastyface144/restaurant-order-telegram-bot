import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

from database import db  # noqa: E402
from database.demo_data import seed_if_empty  # noqa: E402


@pytest.fixture
async def database():
    """Чистая in-memory база с демо-меню."""
    await db.connect(":memory:")
    await seed_if_empty()
    try:
        yield db
    finally:
        await db.close()


_root_router = None


@pytest.fixture
async def harness(database):
    """Бот со всеми роутерами поверх фейкового Telegram."""
    global _root_router
    from handlers import setup_routers
    from utils import screen

    from .telegram_mock import Harness

    # Роутеры aiogram можно подключить только один раз — собираем дерево однажды
    # и перед каждым тестом отцепляем его от диспетчера предыдущего теста.
    if _root_router is None:
        _root_router = setup_routers()
    _root_router._parent_router = None

    from handlers.middlewares import known_users

    known_users.clear()
    screen._screens.clear()
    h = Harness.create(_root_router)
    yield h
    await h.bot.session.close()


@pytest.fixture
def always_open(monkeypatch):
    """Заведение работает круглосуточно — чтобы тесты не зависели от времени запуска."""
    from datetime import time

    import config

    monkeypatch.setattr(config, "WORKING_HOURS", {d: (time(0, 0), time(23, 59)) for d in range(7)})
    monkeypatch.setattr(config, "LAST_ORDER_BEFORE_CLOSE_MINUTES", 0)
