"""Обработчики «на всякий случай»: устаревшие кнопки и сообщения вне сценария."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from .start import show_main_menu

router = Router(name="fallback")


@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    # Например, кнопка из старого сообщения после перезапуска бота
    await callback.answer("Эта кнопка устарела. Нажмите /start, чтобы открыть меню.", show_alert=True)


@router.message(F.chat.type == "private")
async def unknown_message(message: Message, bot: Bot) -> None:
    await show_main_menu(
        bot, message.chat.id, message.from_user.id, force_new=True,
        notice="🤖 Я понимаю кнопки — выберите, что вас интересует 👇",
    )
