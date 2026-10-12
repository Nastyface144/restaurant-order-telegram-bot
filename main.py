"""Точка входа: python main.py"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

import config
from database import db
from database.demo_data import seed_if_empty
from handlers import setup_routers
from orders import scheduler

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # aiogram очень разговорчив на уровне INFO при каждом апдейте
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def set_commands(bot: Bot) -> None:
    """Меню команд: /start для всех, /admin — только администраторам."""
    client = [BotCommand(command="start", description="Главное меню")]
    await bot.set_my_commands(client, scope=BotCommandScopeDefault())
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                client + [BotCommand(command="admin", description="Админ-панель")],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramAPIError:  # админ мог ещё ни разу не написать боту
            logger.warning("Не удалось установить команды для администратора %s — пусть напишет боту /start", admin_id)


async def main() -> None:
    setup_logging()
    for warning in config.validate():
        logger.warning(warning)

    await db.connect(config.DB_PATH)
    await seed_if_empty()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(setup_routers())

    logger.info("Бот «%s» запускается", config.VENUE_NAME)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await set_commands(bot)
        await scheduler.start(bot)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        await db.close()
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
    except TelegramUnauthorizedError:
        print("Ошибка запуска: Telegram не принял BOT_TOKEN — проверьте токен в .env", file=sys.stderr)
        sys.exit(1)
    except TelegramNetworkError as exc:
        print(f"Ошибка запуска: нет связи с Telegram ({exc.message})", file=sys.stderr)
        sys.exit(1)
