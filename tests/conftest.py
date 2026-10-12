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
