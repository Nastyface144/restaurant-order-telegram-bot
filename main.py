"""Точка входа: python main.py"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
from handlers import setup_routers

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # aiogram очень разговорчив на уровне INFO при каждом апдейте
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    for warning in config.validate():
        logger.warning(warning)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(setup_routers())

    logger.info("Бот «%s» запускается", config.VENUE_NAME)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except config.ConfigError as exc:
        # Ошибки конфигурации — понятное сообщение без трейсбека
        print(f"Ошибка запуска: {exc}", file=sys.stderr)
        sys.exit(1)
