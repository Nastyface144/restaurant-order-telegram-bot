"""«Экран» бота — одно сообщение, которое редактируется, а не присылается заново.

Если тип сообщения меняется (текст ↔ фото) или старое сообщение отредактировать
нельзя (удалено, старше 48 часов, это счёт на оплату), бот присылает новое
и удаляет старое — так в чате всё равно остаётся одно актуальное сообщение.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

logger = logging.getLogger(__name__)

# chat_id → (message_id, это фото?). В памяти: после перезапуска бот просто пришлёт новый экран.
_screens: dict[int, tuple[int, bool]] = {}

PhotoType = str | FSInputFile | BufferedInputFile


def remember(message: Message) -> None:
    _screens[message.chat.id] = (message.message_id, bool(message.photo))


def forget(chat_id: int) -> None:
    _screens.pop(chat_id, None)


def current_screen_id(chat_id: int) -> int | None:
    screen = _screens.get(chat_id)
    return screen[0] if screen else None


def _is_not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in str(exc)


async def _safe_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        # Сообщения старше 48 часов удалить нельзя — не страшно
        pass


async def show(
    bot: Bot,
    chat_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
    *,
    photo: PhotoType | None = None,
    message: Message | None = None,
    force_new: bool = False,
) -> Message | None:
    """Показывает экран.

    message — сообщение с кнопкой, которую нажали (из callback). Если не передано,
    редактируется последний экран этого чата. force_new — всегда прислать новое
    сообщение (например, после /start), а старое удалить.

    Возвращает отправленное/отредактированное сообщение (нужно для кэша file_id фото)
    или None, если Telegram ответил «сообщение не изменилось».
    """
    if message is not None and isinstance(message, Message):
        target: tuple[int, bool] | None = (message.message_id, bool(message.photo))
        editable = bool(message.text or message.photo)
    else:
        target = _screens.get(chat_id)
        editable = target is not None

    if target and editable and not force_new:
        target_id, target_is_photo = target
        try:
            result = None
            if photo is not None and target_is_photo:
                result = await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=target_id,
                    media=InputMediaPhoto(media=photo, caption=text),
                    reply_markup=keyboard,
                )
            elif photo is None and not target_is_photo:
                result = await bot.edit_message_text(
                    chat_id=chat_id, message_id=target_id, text=text, reply_markup=keyboard
                )
            if isinstance(result, Message):
                remember(result)
                return result
        except TelegramBadRequest as exc:
            if _is_not_modified(exc):
                _screens[chat_id] = target
                return None
            logger.debug("Не удалось отредактировать экран, пришлём новый: %s", exc)

    if photo is not None:
        sent = await bot.send_photo(chat_id, photo=photo, caption=text, reply_markup=keyboard)
    else:
        sent = await bot.send_message(chat_id, text, reply_markup=keyboard)

    old_id = target[0] if target else None
    if old_id and old_id != sent.message_id:
        await _safe_delete(bot, chat_id, old_id)
    remember(sent)
    return sent


async def delete_user_input(message: Message) -> None:
    """Удаляет сообщение, которое пользователь ввёл (адрес, телефон…), чтобы чат оставался чистым."""
    try:
        await message.delete()
    except TelegramAPIError:
        pass
