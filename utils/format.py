"""Форматирование текста для сообщений."""

from __future__ import annotations

import html
import re

import config

NBSP = " "


def money(amount: int) -> str:
    """1250 → «1 250 ₽» (с неразрывными пробелами, чтобы не переносилось)."""
    return f"{amount:,}".replace(",", NBSP) + NBSP + config.CURRENCY_SIGN


def esc(text: object) -> str:
    """Экранирование пользовательского текста для parse_mode=HTML."""
    return html.escape(str(text), quote=False)


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(3, "позиция", "позиции", "позиций") → «позиции»."""
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def normalize_phone(raw: str) -> str | None:
    """Приводит российский номер к виду +7XXXXXXXXXX. Иностранные номера оставляет с «+»."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits
    if raw.strip().startswith("+") and 10 <= len(digits) <= 15:
        return "+" + digits
    return None


def format_phone(phone: str | None) -> str:
    """+79991234567 → +7 999 123-45-67."""
    if not phone:
        return "—"
    if phone.startswith("+7") and len(phone) == 12:
        d = phone[2:]
        return f"+7{NBSP}{d[:3]}{NBSP}{d[3:6]}-{d[6:8]}-{d[8:]}"
    return phone


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
