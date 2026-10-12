"""Фейковый Telegram для сквозных тестов: бот работает как настоящий,
но вместо сети запросы попадают в FakeSession, которая отвечает правдоподобными объектами
и запоминает сообщения в чатах. Harness умеет «писать боту» и «нажимать кнопки» по тексту.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    AnswerPreCheckoutQuery,
    CopyMessage,
    DeleteMessage,
    EditMessageMedia,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendInvoice,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import InlineKeyboardMarkup, Message, MessageId, Update, User

BOT_ID = 4242


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.messages: dict[tuple[int, int], dict[str, Any]] = {}
        self._ids = itertools.count(1000)
        self.raise_for: dict[type, Exception] = {}
        self.blocked_chats: set[int] = set()

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError
        yield b""

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _chat(chat_id: int) -> dict:
        if chat_id < 0:
            return {"id": chat_id, "type": "supergroup", "title": "Staff"}
        return {"id": chat_id, "type": "private", "first_name": "User"}

    def _store(self, chat_id: int, message_id: int, **fields) -> dict:
        data = {
            "message_id": message_id,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": self._chat(chat_id),
            "from": {"id": BOT_ID, "is_bot": True, "first_name": "Bot", "username": "test_bot"},
            **fields,
        }
        self.messages[(chat_id, message_id)] = data
        return data

    @staticmethod
    def _markup(markup) -> dict | None:
        if isinstance(markup, InlineKeyboardMarkup):
            return markup.model_dump(exclude_none=True)
        return None

    def _photo(self, media) -> list[dict]:
        file_id = media if isinstance(media, str) else f"file-{next(self._ids)}"
        return [{"file_id": file_id, "file_unique_id": file_id, "width": 960, "height": 640}]

    # --- core --------------------------------------------------------------

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> Any:
        self.requests.append(method)
        for cls, exc in self.raise_for.items():
            if isinstance(method, cls):
                raise exc
        chat_id = getattr(method, "chat_id", None)
        if chat_id in self.blocked_chats:
            from aiogram.exceptions import TelegramForbiddenError
            raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")

        if isinstance(method, GetMe):
            return User(id=BOT_ID, is_bot=True, first_name="Bot", username="test_bot")
        if isinstance(method, SendMessage):
            data = self._store(method.chat_id, next(self._ids), text=method.text,
                               reply_markup=self._markup(method.reply_markup))
            return Message.model_validate(data, context={"bot": bot})
        if isinstance(method, SendPhoto):
            data = self._store(method.chat_id, next(self._ids), caption=method.caption,
                               photo=self._photo(method.photo), reply_markup=self._markup(method.reply_markup))
            return Message.model_validate(data, context={"bot": bot})
        if isinstance(method, SendInvoice):
            data = self._store(
                method.chat_id, next(self._ids),
                invoice={"title": method.title, "description": method.description, "start_parameter": "",
                         "currency": method.currency, "total_amount": sum(p.amount for p in method.prices)},
                reply_markup=self._markup(method.reply_markup),
            )
            data["_payload"] = method.payload
            return Message.model_validate(data, context={"bot": bot})
        if isinstance(method, EditMessageText):
            old = self.messages.get((method.chat_id, method.message_id))
            if old is None or "text" not in old:
                from aiogram.exceptions import TelegramBadRequest
                raise TelegramBadRequest(method=method, message="Bad Request: message can't be edited")
            data = self._store(method.chat_id, method.message_id, text=method.text,
                               reply_markup=self._markup(method.reply_markup))
            return Message.model_validate(data, context={"bot": bot})
        if isinstance(method, EditMessageMedia):
            old = self.messages.get((method.chat_id, method.message_id))
            if old is None or "photo" not in old:
                from aiogram.exceptions import TelegramBadRequest
                raise TelegramBadRequest(method=method, message="Bad Request: message can't be edited")
            data = self._store(method.chat_id, method.message_id, caption=method.media.caption,
                               photo=self._photo(method.media.media), reply_markup=self._markup(method.reply_markup))
            return Message.model_validate(data, context={"bot": bot})
        if isinstance(method, EditMessageReplyMarkup):
            old = self.messages.get((method.chat_id, method.message_id))
            if old is None:
                return True
            old["reply_markup"] = self._markup(method.reply_markup)
            return Message.model_validate(old, context={"bot": bot})
        if isinstance(method, DeleteMessage):
            self.messages.pop((method.chat_id, method.message_id), None)
            return True
        if isinstance(method, CopyMessage):
            return MessageId(message_id=next(self._ids))
        if isinstance(method, (AnswerCallbackQuery, AnswerPreCheckoutQuery)):
            return True
        return True

    # --- inspection --------------------------------------------------------

    def chat_messages(self, chat_id: int) -> list[dict]:
        return [m for (c, _), m in sorted(self.messages.items()) if c == chat_id]

    def last_message(self, chat_id: int) -> dict:
        messages = self.chat_messages(chat_id)
        assert messages, f"В чате {chat_id} нет сообщений"
        return messages[-1]

    def calls(self, cls: type) -> list:
        return [r for r in self.requests if isinstance(r, cls)]


class Harness:
    """Имитирует пользователей: пишет боту и нажимает кнопки."""

    def __init__(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        self.dp = dp
        self.bot = bot
        self.session = session
        self._update_ids = itertools.count(1)
        self._user_msg_ids = itertools.count(1)

    @classmethod
    def create(cls, router) -> Harness:
        session = FakeSession()
        bot = Bot("123456:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(router)
        return cls(dp, bot, session)

    @staticmethod
    def user(user_id: int, name: str = "Иван") -> dict:
        return {"id": user_id, "is_bot": False, "first_name": name}

    async def feed(self, payload: dict) -> None:
        update = Update.model_validate({"update_id": next(self._update_ids), **payload}, context={"bot": self.bot})
        await self.dp.feed_update(self.bot, update)

    async def send(self, user_id: int, text: str | None = None, **extra) -> None:
        message = {
            "message_id": next(self._user_msg_ids),
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": FakeSession._chat(user_id),
            "from": self.user(user_id),
            **extra,
        }
        if text is not None:
            message["text"] = text
            if text.startswith("/"):
                message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        await self.feed({"message": message})

    def screen(self, chat_id: int) -> dict:
        return self.session.last_message(chat_id)

    def screen_text(self, chat_id: int) -> str:
        msg = self.screen(chat_id)
        return msg.get("text") or msg.get("caption") or ""

    def buttons(self, chat_id: int, message: dict | None = None) -> list[str]:
        msg = message or self.screen(chat_id)
        rows = (msg.get("reply_markup") or {}).get("inline_keyboard", [])
        return [b["text"] for row in rows for b in row]

    async def click(self, chat_id: int, text: str, *, user_id: int | None = None, exact: bool = False,
                    message: dict | None = None) -> None:
        """Нажимает кнопку, текст которой содержит `text`, на последнем сообщении чата."""
        msg = message or self.screen(chat_id)
        rows = (msg.get("reply_markup") or {}).get("inline_keyboard", [])
        for row in rows:
            for button in row:
                if (button["text"] == text) if exact else (text in button["text"]):
                    if "callback_data" not in button:
                        raise AssertionError(f"Кнопка «{button['text']}» — ссылка, а не callback")
                    await self.click_data(chat_id, button["callback_data"], msg, user_id=user_id)
                    return
        raise AssertionError(f"Нет кнопки «{text}». Есть: {self.buttons(chat_id, msg)}")

    async def click_data(self, chat_id: int, data: str, message: dict, *, user_id: int | None = None) -> None:
        user_id = user_id or chat_id
        await self.feed({
            "callback_query": {
                "id": str(next(self._update_ids)),
                "from": self.user(user_id),
                "chat_instance": "ci",
                "message": {k: v for k, v in message.items() if not k.startswith("_")},
                "data": data,
            }
        })
