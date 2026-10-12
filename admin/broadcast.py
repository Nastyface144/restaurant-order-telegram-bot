"""Рассылка сообщения всем клиентам бота с соблюдением лимитов Telegram."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from database import users

logger = logging.getLogger(__name__)

# Telegram разрешает ~30 сообщений в секунду разным пользователям — держимся с запасом
SEND_INTERVAL = 0.05
PROGRESS_EVERY = 25


@dataclass
class BroadcastResult:
    total: int = 0
    sent: int = 0
    blocked: int = 0
    failed: int = 0


ProgressCallback = Callable[[BroadcastResult], Awaitable[None]]


async def _copy(bot: Bot, user_id: int, from_chat_id: int, message_id: int) -> None:
    try:
        await bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)
    except TelegramRetryAfter as exc:
        logger.info("Флуд-контроль: пауза %s с", exc.retry_after)
        await asyncio.sleep(exc.retry_after)
        await bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)


async def broadcast(
    bot: Bot,
    from_chat_id: int,
    message_id: int,
    *,
    exclude: set[int] | None = None,
    on_progress: ProgressCallback | None = None,
) -> BroadcastResult:
    """Копирует сообщение (текст или фото с подписью) всем активным клиентам."""
    recipients = [u for u in await users.get_active_user_ids() if u not in (exclude or set())]
    result = BroadcastResult(total=len(recipients))
    for index, user_id in enumerate(recipients, 1):
        try:
            await _copy(bot, user_id, from_chat_id, message_id)
            result.sent += 1
        except TelegramForbiddenError:
            result.blocked += 1
            await users.mark_blocked(user_id)
        except TelegramAPIError as exc:
            result.failed += 1
            logger.warning("Рассылка: не доставлено пользователю %s: %s", user_id, exc)
        if on_progress and index % PROGRESS_EVERY == 0 and index < result.total:
            await on_progress(result)
        await asyncio.sleep(SEND_INTERVAL)
    logger.info("Рассылка завершена: %s", result)
    return result
