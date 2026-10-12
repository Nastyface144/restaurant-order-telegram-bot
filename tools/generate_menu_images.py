"""Генерирует картинки-заглушки для демо-меню (assets/menu/*.jpg).

Запуск: python tools/generate_menu_images.py  (нужен Pillow: pip install pillow)
Для реального заведения просто замените файлы фотографиями блюд
или укажите в меню URL / file_id.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "menu"
EMOJI_FONT = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
TEXT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SMALL_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

W, H = 960, 640

# файл: (эмодзи, название, цвет сверху, цвет снизу)
IMAGES = {
    "margherita": ("🍕", "Маргарита", "#e94b3c", "#f6a04d"),
    "pepperoni": ("🍕", "Пепперони", "#b5262d", "#e2603f"),
    "four_cheese": ("🧀", "Четыре сыра", "#e8a33d", "#f7d774"),
    "bbq": ("🍕", "Барбекю", "#6b3a26", "#c0703c"),
    "fries": ("🍟", "Картофель фри", "#f2a516", "#fbd75b"),
    "wings": ("🍗", "Куриные крылья", "#c4522a", "#eb9b4f"),
    "garlic_bread": ("🥖", "Чесночный хлеб", "#a67c3d", "#e0bb73"),
    "lemonade": ("🍋", "Лимонад домашний", "#3fae6a", "#c6e86b"),
    "mors": ("🍒", "Морс клюквенный", "#8e1b3f", "#d6496b"),
    "cappuccino": ("☕", "Капучино", "#5b3a29", "#a77b5a"),
    "cheesecake": ("🍰", "Чизкейк Нью-Йорк", "#d77fa1", "#f6c8d6"),
    "tiramisu": ("🍮", "Тирамису", "#6f4e37", "#c9a27e"),
}


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def gradient(top: str, bottom: str) -> Image.Image:
    t, b = _hex(top), _hex(bottom)
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        k = y / (H - 1)
        draw.line([(0, y), (W, y)], fill=tuple(round(t[i] + (b[i] - t[i]) * k) for i in range(3)))
    return img


def render_emoji(char: str, size: int) -> Image.Image:
    # Noto Color Emoji — растровый шрифт, рисуется только в размере 109
    font = ImageFont.truetype(EMOJI_FONT, 109)
    canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((80, 80), char, font=font, embedded_color=True, anchor="mm")
    canvas = canvas.crop(canvas.getbbox())
    return canvas.resize((size, round(size * canvas.height / canvas.width)), Image.LANCZOS)


def make(name: str, emoji: str, title: str, top: str, bottom: str) -> None:
    img = gradient(top, bottom)
    draw = ImageDraw.Draw(img, "RGBA")
    # мягкий круг-«тарелка» под эмодзи
    cx, cy, r = W // 2, 270, 190
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 60))
    draw.ellipse((cx - r + 22, cy - r + 22, cx + r - 22, cy + r - 22), fill=(255, 255, 255, 70))

    pic = render_emoji(emoji, 250)
    img.paste(pic, (cx - pic.width // 2, cy - pic.height // 2), pic)

    title_font = ImageFont.truetype(TEXT_FONT, 58)
    small_font = ImageFont.truetype(SMALL_FONT, 26)
    draw.text((W // 2 + 2, 538), title, font=title_font, fill=(0, 0, 0, 70), anchor="mm")
    draw.text((W // 2, 535), title, font=title_font, fill="white", anchor="mm")
    draw.text((W // 2, 600), "Пицца у дома · демо-фото", font=small_font, fill=(255, 255, 255, 200), anchor="mm")

    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.jpg", quality=86, optimize=True)


def main() -> None:
    for name, (emoji, title, top, bottom) in IMAGES.items():
        make(name, emoji, title, top, bottom)
        print(f"✓ {name}.jpg")


if __name__ == "__main__":
    main()
