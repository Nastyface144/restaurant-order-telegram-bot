"""Мидлвари: регистрация пользователя в БД."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from database import users

logger = logging.getLogger(__name__)

# user_id → (имя, username), уже сохранённые в БД
known_users: dict[int, tuple[str, str | None]] = {}


class UserMiddleware(BaseMiddleware):
    """Сохраняет клиента в БД при первом обращении и при смене имени.

    Чтобы не писать в базу на каждое нажатие, уже известные пользователи
    кэшируются в памяти.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        chat = data.get("event_chat")
        if user and not user.is_bot and chat is not None and chat.type == "private":
            snapshot = (user.full_name, user.username)
            if known_users.get(user.id) != snapshot:
                try:
                    await users.upsert_user(user.id, user.full_name, user.username)
                    known_users[user.id] = snapshot
                except Exception:
                    # Сбой БД не должен ломать обработку — попробуем в следующий раз
                    logger.exception("Не удалось сохранить пользователя %s", user.id)
        return await handler(event, data)
