"""Глобальный обработчик ошибок: бот не падает, а пользователь видит понятное сообщение."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)
router = Router(name="errors")

USER_ERROR_TEXT = "😔 Что-то пошло не так. Попробуйте ещё раз или нажмите /start"


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    exc = event.exception

    # Безобидные ошибки Telegram: повторное нажатие, сообщение не изменилось и т. п.
    if isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc):
        return True

    logger.exception("Ошибка при обработке update %s", event.update.update_id, exc_info=exc)

    update = event.update
    try:
        if update.callback_query:
            await update.callback_query.answer(USER_ERROR_TEXT, show_alert=True)
        elif update.message and update.message.chat.type == "private":
            await update.message.answer(USER_ERROR_TEXT)
    except TelegramAPIError:
        logger.warning("Не удалось сообщить пользователю об ошибке", exc_info=True)
    return True
