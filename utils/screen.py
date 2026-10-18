"""«Экран» бота — одно сообщение, которое редактируется, а не присылается заново.

Почти каждый экран — это картинка-баннер с подписью и кнопками. Если картинка та
же, что уже на экране, меняется только подпись (без мигания). Если меняется
картинка — подменяется медиа в том же сообщении. Если сообщение отредактировать
нельзя (удалено, старше 48 часов, это счёт на оплату), бот присылает новое и
удаляет старое — в чате всё равно остаётся одно актуальное сообщение.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

import config

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
BANNERS_DIR = config.BASE_DIR / "assets" / "banners"

PhotoSource = str | FSInputFile | BufferedInputFile


@dataclass(frozen=True)
class Picture:
    key: str              # стабильный идентификатор картинки (путь, URL, «item:5»)
    source: PhotoSource   # что отправить в Telegram: file_id, URL или файл


@dataclass(frozen=True)
class _Screen:
    message_id: int
    picture_key: str | None  # None — текстовое сообщение


# chat_id → текущий экран. В памяти: после перезапуска бот просто пришлёт новый экран.
_screens: dict[int, _Screen] = {}
# ключ картинки → file_id в Telegram, чтобы не загружать один и тот же файл повторно
_file_ids: dict[str, str] = {}


def picture_from_file(path: Path, key: str | None = None) -> Picture | None:
    key = key or str(path)
    if key in _file_ids:
        return Picture(key, _file_ids[key])
    if not path.is_file():
        return None
    return Picture(key, FSInputFile(path))


def banner(name: str) -> Picture | None:
    """Баннер экрана из assets/banners/<name>.jpg (None, если файла нет — экран будет текстовым)."""
    return picture_from_file(BANNERS_DIR / f"{name}.jpg", key=f"banner:{name}")


def remember(message: Message, picture_key: str | None = None) -> None:
    if message.photo and picture_key is None:
        picture_key = "?"
    _screens[message.chat.id] = _Screen(message.message_id, picture_key if message.photo else None)


def forget(chat_id: int) -> None:
    _screens.pop(chat_id, None)


def current_screen_id(chat_id: int) -> int | None:
    screen = _screens.get(chat_id)
    return screen.message_id if screen else None


def visible_length(html: str) -> int:
    """Длина текста так, как её считает Telegram (без HTML-тегов)."""
    text = re.sub(r"<[^>]+>", "", html)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&quot;", '"')):
        text = text.replace(entity, char)
    return len(text)


def _is_not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in str(exc)


def _store_file_id(picture: Picture, message: Message) -> None:
    if message.photo and not isinstance(picture.source, str):
        _file_ids[picture.key] = message.photo[-1].file_id


async def _safe_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        pass  # сообщения старше 48 часов удалить нельзя — не страшно


async def show(
    bot: Bot,
    chat_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
    *,
    picture: Picture | None = None,
    message: Message | None = None,
    force_new: bool = False,
) -> Message | None:
    """Показывает экран.

    message — сообщение с кнопкой, которую нажали (из callback). Если не передано,
    редактируется последний экран этого чата. force_new — прислать новое сообщение,
    а старое удалить (например, после /start).

    Возвращает отправленное или отредактированное сообщение, либо None,
    если Telegram ответил «сообщение не изменилось».
    """
    if picture is not None and visible_length(text) > CAPTION_LIMIT:
        picture = None  # подпись к фото ограничена 1024 символами — покажем текстом

    known = _screens.get(chat_id)
    if isinstance(message, Message):
        if known and known.message_id == message.message_id:
            target: _Screen | None = known
        else:
            target = _Screen(message.message_id, "?" if message.photo else None)
        editable = bool(message.text or message.photo)
    else:
        target = known
        editable = target is not None

    if target and editable and not force_new:
        try:
            result = None
            if picture is not None and target.picture_key == picture.key:
                result = await bot.edit_message_caption(
                    chat_id=chat_id, message_id=target.message_id, caption=text, reply_markup=keyboard
                )
            elif picture is not None and target.picture_key is not None:
                result = await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=target.message_id,
                    media=InputMediaPhoto(media=picture.source, caption=text),
                    reply_markup=keyboard,
                )
            elif picture is None and target.picture_key is None:
                result = await bot.edit_message_text(
                    chat_id=chat_id, message_id=target.message_id, text=text, reply_markup=keyboard
                )
            if isinstance(result, Message):
                if picture is not None:
                    _store_file_id(picture, result)
                remember(result, picture.key if picture else None)
                return result
        except TelegramBadRequest as exc:
            if _is_not_modified(exc):
                _screens[chat_id] = target
                return None
            if picture is not None:
                _file_ids.pop(picture.key, None)  # file_id мог устареть — ниже отправим файл заново
            logger.debug("Не удалось отредактировать экран, пришлём новый: %s", exc)

    if picture is not None:
        sent = await bot.send_photo(chat_id, photo=picture.source, caption=text, reply_markup=keyboard)
        _store_file_id(picture, sent)
    else:
        sent = await bot.send_message(chat_id, text, reply_markup=keyboard)

    if target and target.message_id != sent.message_id:
        await _safe_delete(bot, chat_id, target.message_id)
    remember(sent, picture.key if picture else None)
    return sent


async def delete_user_input(message: Message) -> None:
    """Удаляет сообщение, которое ввёл пользователь (адрес, телефон…), чтобы чат оставался чистым."""
    try:
        await message.delete()
    except TelegramAPIError:
        pass
