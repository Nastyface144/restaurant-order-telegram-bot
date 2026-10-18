"""Скриншоты экранов бота без Telegram: бот проходит сценарий на фейковом Telegram
(tests/telegram_mock.py), а каждый экран рисуется так, как он выглядит в приложении
(тёмная тема). Результат — docs/screens/*.png и общий коллаж docs/screens.png.

Запуск: python tools/preview_screens.py   (нужен Pillow)
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import sys
from datetime import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "0:preview")

import config  # noqa: E402

OUT = ROOT / "docs" / "screens"
W = 760                      # ширина «телефона»
PAD = 24
BUBBLE_W = W - PAD * 2
BG = (14, 22, 33)
BUBBLE = (24, 37, 51)
TEXT = (245, 245, 245)
MUTED = (140, 160, 180)
QUOTE_BAR = (100, 168, 230)
QUOTE_BG = (32, 50, 70)
BUTTON_COLORS = {
    None: (43, 63, 84),
    "primary": (51, 144, 236),
    "success": (49, 168, 87),
    "danger": (222, 76, 70),
}

FONTS = {
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "italic": ["C:/Windows/Fonts/segoeuii.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"],
    "symbol": ["C:/Windows/Fonts/seguisym.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "emoji": ["C:/Windows/Fonts/seguiemj.ttf", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"],
}
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _font_cache:
        path = next(p for p in FONTS[kind] if Path(p).is_file())
        _font_cache[key] = ImageFont.truetype(path, 109 if "Noto" in path else size)
    return _font_cache[key]


def char_kind(ch: str) -> str:
    o = ord(ch)
    if o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0x2300 <= o <= 0x23FF or o in (0x2B50, 0xFE0F, 0x200D):
        return "emoji"
    if 0x2190 <= o <= 0x21FF or 0x2500 <= o <= 0x25FF or 0xFF00 <= o <= 0xFFEF:
        return "symbol"
    return "text"


def segments(text: str):
    """Делит строку на куски одного шрифта: текст / символы / эмодзи (вместе с селекторами)."""
    out: list[tuple[str, str]] = []
    for ch in text:
        kind = char_kind(ch)
        if ch in ("\ufe0f", "\u200d") and out:
            out[-1] = (out[-1][0] + ch, out[-1][1])
            continue
        if out and out[-1][1] == kind and kind != "emoji":
            out[-1] = (out[-1][0] + ch, kind)
        elif out and out[-1][1] == "emoji" and kind == "emoji" and out[-1][0][-1] == "\u200d":
            out[-1] = (out[-1][0] + ch, kind)
        else:
            out.append((ch, kind))
    return out


class Painter:
    def __init__(self, draw: ImageDraw.ImageDraw, size: int = 24):
        self.draw = draw
        self.size = size

    def _font(self, kind: str, style: str):
        if kind == "emoji":
            return font("emoji", self.size)
        if kind == "symbol":
            return font("symbol", self.size)
        return font(style, self.size)

    def width(self, text: str, style: str = "regular") -> float:
        return sum(self._seg_width(t, k, style) for t, k in segments(text))

    def _seg_width(self, text: str, kind: str, style: str) -> float:
        if kind == "emoji":
            return self.size * 1.2 * len([c for c in text if c not in "\ufe0f\u200d"]) if text.strip() else 0
        return self.draw.textlength(text, font=self._font(kind, style))

    def text(self, xy, text: str, style: str = "regular", fill=TEXT, strike: bool = False) -> float:
        x, y = xy
        start = x
        for seg, kind in segments(text):
            w = self._seg_width(seg, kind, style)
            if kind == "emoji":
                ef = font("emoji", self.size)
                canvas = Image.new("RGBA", (int(w) + 8, self.size * 2), (0, 0, 0, 0))
                ImageDraw.Draw(canvas).text((0, self.size // 2), seg, font=ef, embedded_color=True)
                if "Noto" in ef.path:
                    canvas = canvas.resize((int(w) + 8, self.size * 2))
                self.draw._image.alpha_composite(canvas, (int(x), int(y - self.size // 2 + 2)))
            else:
                self.draw.text((x, y), seg, font=self._font(kind, style), fill=fill)
            x += w
        if strike:
            self.draw.line((start, y + self.size * 0.65, x, y + self.size * 0.65), fill=fill, width=2)
        return x - start


def parse_runs(line: str) -> list[tuple[str, str, bool]]:
    """Строка с <b>/<i>/<s> → [(текст, стиль, зачёркнут)]."""
    runs, bold, italic, strike = [], False, False, False
    for part in re.split(r"(<[^>]+>)", line):
        if not part:
            continue
        tag = part.lower()
        if tag in ("<b>", "</b>"):
            bold = tag == "<b>"
        elif tag in ("<i>", "</i>"):
            italic = tag == "<i>"
        elif tag in ("<s>", "</s>"):
            strike = tag == "<s>"
        elif part.startswith("<"):
            continue
        else:
            style = "bold" if bold else "italic" if italic else "regular"
            runs.append((html.unescape(part), style, strike))
    return runs


def layout(painter: Painter, html_text: str, max_w: int) -> list[tuple[list, bool]]:
    """Перенос строк: [(список кусков, это цитата?)]."""
    result = []
    quote = False
    for raw in html_text.split("\n"):
        line = raw
        opens = "<blockquote" in line
        closes = "</blockquote>" in line
        if opens:
            quote = True
        line = re.sub(r"</?blockquote[^>]*>", "", line)
        width = max_w - (28 if quote else 0)
        current, cur_w = [], 0.0
        for text, style, strike in parse_runs(line) or [("", "regular", False)]:
            for word in re.split(r"(\s+)", text):
                if not word:
                    continue
                w = painter.width(word, style)
                if cur_w + w > width and current and word.strip():
                    result.append((current, quote))
                    current, cur_w = [], 0.0
                    if not word.strip():
                        continue
                current.append((word, style, strike))
                cur_w += w
        result.append((current, quote))
        if closes:
            quote = False
    return result


def truncate_to(painter: Painter, text: str, max_w: float) -> str:
    if painter.width(text, "bold") <= max_w:
        return text
    while text and painter.width(text + "…", "bold") > max_w:
        text = text[:-1]
    return text + "…"


def render_message(message: dict, files: dict[str, str]) -> Image.Image:
    caption = message.get("caption") or message.get("text") or ""
    photo_path = None
    if message.get("photo"):
        photo_path = files.get(message["photo"][-1]["file_id"])
    markup = (message.get("reply_markup") or {}).get("inline_keyboard", [])

    scratch = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    painter = Painter(scratch)
    lines = layout(painter, caption, BUBBLE_W - 40)
    line_h = 34
    photo_h = int(BUBBLE_W * 800 / 1280) if photo_path else 0
    text_h = len(lines) * line_h + 36
    buttons_h = len(markup) * 62
    height = PAD + photo_h + text_h + 10 + buttons_h + PAD

    img = Image.new("RGBA", (W, height), (*BG, 255))
    draw = ImageDraw.Draw(img)
    painter = Painter(draw)
    top = PAD
    draw.rounded_rectangle((PAD, top, PAD + BUBBLE_W, top + photo_h + text_h), radius=22, fill=BUBBLE)
    if photo_path:
        photo = Image.open(photo_path).convert("RGBA").resize((BUBBLE_W, photo_h), Image.LANCZOS)
        mask = Image.new("L", photo.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, BUBBLE_W, photo_h + 30), radius=22, fill=255)
        img.paste(photo, (PAD, top), mask)
    y = top + photo_h + 18
    for runs, quote in lines:
        x = PAD + 20
        if quote:
            draw.rectangle((x, y - 2, PAD + BUBBLE_W - 20, y + line_h - 2), fill=QUOTE_BG)
            draw.rectangle((x, y - 2, x + 4, y + line_h - 2), fill=QUOTE_BAR)
            x += 18
        for word, style, strike in runs:
            x += painter.text((x, y), word, style, fill=MUTED if style == "italic" else TEXT, strike=strike)
        y += line_h

    y = top + photo_h + text_h + 10
    for row in markup:
        n = len(row)
        bw = (BUBBLE_W - 8 * (n - 1)) / n
        for i, btn in enumerate(row):
            x0 = PAD + i * (bw + 8)
            color = BUTTON_COLORS.get(btn.get("style"), BUTTON_COLORS[None])
            draw.rounded_rectangle((x0, y, x0 + bw, y + 54), radius=14, fill=color)
            label = truncate_to(painter, btn["text"], bw - 20)
            tw = painter.width(label, "bold")
            painter.text((x0 + (bw - tw) / 2, y + 12), label, "bold")
        y += 62
    return img


async def scenario() -> list[tuple[str, dict]]:
    from database import db
    from handlers import setup_routers
    from tests.telegram_mock import Harness

    config.WORKING_HOURS = {d: (time(0, 0), time(23, 59)) for d in range(7)}
    config.LAST_ORDER_BEFORE_CLOSE_MINUTES = 0
    config.STAFF_CHAT_ID = -100
    staff, user = -100, 777

    await db.connect(":memory:")
    try:
        return await _walk(Harness.create(setup_routers()), staff, user)
    finally:
        await db.close()  # иначе поток aiosqlite не даст процессу завершиться при ошибке


async def _walk(h, staff: int, user: int) -> list[tuple[str, dict]]:
    from database.demo_data import seed_if_empty

    await seed_if_empty()
    shots: list[tuple[str, dict]] = []

    def snap(name: str, chat: int = user, message: dict | None = None) -> None:
        shots.append((name, dict(message or h.screen(chat))))

    await h.send(user, "/start")
    snap("01_home")
    await h.click(user, "меню")
    snap("02_menu")
    await h.click(user, "Пицца")
    snap("03_category")
    await h.click(user, "Пепперони")
    await h.click(user, "35 см")
    await h.click(user, "Бекон")
    snap("04_item")
    await h.click(user, "В корзину")
    await h.click(user, "Назад")
    await h.click(user, "Назад")
    await h.click(user, "Напитки")
    await h.click(user, "Лимонад")
    await h.click(user, "В корзину")
    await h.click(user, "🛒 1")
    snap("05_cart")
    await h.click(user, "Оформить")
    await h.click(user, "Доставка")
    await h.send(user, "ул. Садовая, 5, кв. 12")
    snap("06_time")
    await h.click(user, "Как можно скорее")
    await h.send(user, "+7 999 123-45-67")
    await h.send(user, "Домофон 12")
    await h.click(user, "Картой при получении")
    snap("07_confirm")
    await h.click(user, "Подтвердить")
    snap("08_done")
    for label in ("Принять", "Готовится", "Курьер выехал"):
        await h.click(staff, label, user_id=1)
    snap("10_staff", staff)
    notification = [m for m in h.session.chat_messages(user) if "Курьер выехал" in (m.get("text") or "")][-1]
    snap("09_notification", message=notification)
    await h.send(user, "/start")
    snap("11_home_active")
    files = h.session.files
    return [(name, {**msg, "_files": files}) for name, msg in shots]


def main() -> None:
    shots = asyncio.run(scenario())
    OUT.mkdir(parents=True, exist_ok=True)
    images = []
    for name, msg in sorted(shots):
        img = render_message(msg, msg["_files"]).convert("RGB")
        img.save(OUT / f"{name}.png", optimize=True)
        images.append(img)
        print(f"+ docs/screens/{name}.png")

    # коллаж для README: 4 колонки
    cols = 4
    scale = 0.5
    thumbs = [im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS) for im in images]
    col_w = int(W * scale)
    col_heights = [0] * cols
    placed = []
    for thumb in thumbs:
        c = col_heights.index(min(col_heights))
        placed.append((thumb, c * col_w, col_heights[c]))
        col_heights[c] += thumb.height
    sheet = Image.new("RGB", (col_w * cols, max(col_heights)), BG)
    for thumb, x, y in placed:
        sheet.paste(thumb, (x, y))
    sheet.save(ROOT / "docs" / "screens.png", optimize=True)
    print("+ docs/screens.png")


if __name__ == "__main__":
    main()
