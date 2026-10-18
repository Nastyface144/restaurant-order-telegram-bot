"""Генерирует картинки бота: баннеры экранов (assets/banners) и фото-заглушки блюд (assets/menu).

Запуск: python tools/generate_images.py  (нужен Pillow: pip install pillow)

Баннеры берут название и адрес из config.py — после смены названия заведения
перезапустите скрипт. Для реального заведения картинки блюд лучше заменить
настоящими фотографиями (те же имена файлов, соотношение сторон 16:10).
"""

from __future__ import annotations

import math
import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "0:generator")

import config  # noqa: E402

W, H = 1280, 800
MENU_OUT = ROOT / "assets" / "menu"
BANNER_OUT = ROOT / "assets" / "banners"

FONT_CANDIDATES = {
    "black": ["C:/Windows/Fonts/seguibl.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}
EMOJI_CANDIDATES = [
    "C:/Windows/Fonts/seguiemj.ttf",  # векторный (COLR), любой размер
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",  # растровый, только 109 px
]

CREAM = (255, 246, 235)
INK = (34, 28, 24)


def _first_existing(paths: list[str]) -> str:
    for path in paths:
        if Path(path).is_file():
            return path
    raise SystemExit(f"Не найден ни один шрифт из: {paths}")


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_first_existing(FONT_CANDIDATES[kind]), size)


def emoji(char: str, size: int, angle: float = 0) -> Image.Image:
    path = _first_existing(EMOJI_CANDIDATES)
    render = 109 if "Noto" in path else size
    fnt = ImageFont.truetype(path, render)
    canvas = Image.new("RGBA", (render * 2, render * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((render, render), char, font=fnt, embedded_color=True, anchor="mm")
    canvas = canvas.crop(canvas.getbbox())
    scale = size / max(canvas.size)
    canvas = canvas.resize((max(1, round(canvas.width * scale)), max(1, round(canvas.height * scale))), Image.LANCZOS)
    if angle:
        canvas = canvas.rotate(angle, resample=Image.BICUBIC, expand=True)
    return canvas


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, k: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))


def radial_background(inner, outer) -> Image.Image:
    """Мягкий радиальный градиент: светлее в центре композиции."""
    small = Image.new("RGB", (W // 8, H // 8))
    px = small.load()
    cx, cy = small.width * 0.68, small.height * 0.45
    max_d = math.hypot(small.width, small.height) * 0.75
    for y in range(small.height):
        for x in range(small.width):
            k = min(1.0, math.hypot(x - cx, y - cy) / max_d)
            px[x, y] = mix(inner, outer, k ** 1.4)
    return small.resize((W, H), Image.BICUBIC)


def paste_with_shadow(base: Image.Image, sprite: Image.Image, xy: tuple[int, int], blur: int = 18,
                      offset: tuple[int, int] = (0, 14), opacity: int = 90) -> None:
    alpha = sprite.split()[-1]
    shadow = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda a: a * opacity // 255))
    pad = blur * 3
    shadow_canvas = Image.new("RGBA", (sprite.width + pad * 2, sprite.height + pad * 2), (0, 0, 0, 0))
    shadow_canvas.paste(shadow, (pad, pad))
    shadow_canvas = shadow_canvas.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(shadow_canvas, (xy[0] - pad + offset[0], xy[1] - pad + offset[1]))
    base.alpha_composite(sprite, xy)


def circle(size: int, color, alpha: int = 255) -> Image.Image:
    scale = 4
    img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=(*color, alpha))
    return img.resize((size, size), Image.LANCZOS)


def scatter(base: Image.Image, chars: list[str], seed: int, area: tuple[int, int, int, int],
            count: int, size: tuple[int, int], keep_out: tuple[int, int, int] | None = None,
            opacity: int = 255) -> None:
    """Разбрасывает мелкие эмодзи-ингредиенты, не залезая на центральный объект."""
    rnd = random.Random(seed)
    placed: list[tuple[int, int, int]] = []
    tries = 0
    while len(placed) < count and tries < 400:
        tries += 1
        s = rnd.randint(*size)
        x = rnd.randint(area[0], area[2] - s)
        y = rnd.randint(area[1], area[3] - s)
        cx, cy = x + s // 2, y + s // 2
        if keep_out and math.hypot(cx - keep_out[0], cy - keep_out[1]) < keep_out[2] + s * 0.6:
            continue
        if any(math.hypot(cx - px, cy - py) < (s + ps) * 0.75 for px, py, ps in placed):
            continue
        placed.append((cx, cy, s))
        sprite = emoji(rnd.choice(chars), s, angle=rnd.uniform(-35, 35))
        if opacity < 255:
            sprite.putalpha(sprite.split()[-1].point(lambda a: a * opacity // 255))
        paste_with_shadow(base, sprite, (x, y), blur=8, offset=(0, 6), opacity=60)


def rounded_pill(draw: ImageDraw.ImageDraw, xy, text: str, fnt, fill, text_fill) -> int:
    x, y = xy
    tw = draw.textlength(text, font=fnt)
    h = fnt.size + 26
    w = int(tw + 44)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=fill)
    draw.text((x + 22, y + h // 2), text, font=fnt, fill=text_fill, anchor="lm")
    return w


def fit_font(draw: ImageDraw.ImageDraw, text: str, kind: str, size: int, max_width: int) -> ImageFont.FreeTypeFont:
    while size > 30:
        fnt = font(kind, size)
        if draw.textlength(text, font=fnt) <= max_width:
            return fnt
        size -= 4
    return font(kind, size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    """Перенос по словам; короткие предлоги и тире не остаются в конце строки."""
    words: list[str] = []
    for word in text.split():
        if words and (len(words[-1]) <= 2 or words[-1] == "—"):
            words[-1] += " " + word
        else:
            words.append(word)
    lines, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=fnt) <= max_width:
            line = candidate
        else:
            lines.append(line.replace(" ", " "))
            line = word
    if line:
        lines.append(line.replace(" ", " "))
    return lines


# ---------------------------------------------------------------------------
# Блюда
# ---------------------------------------------------------------------------

# файл: (главный эмодзи, ингредиенты вокруг, цвет фона)
DISHES = {
    "margherita": ("🍕", ["🍅", "🌿", "🧀"], "#F6C9A8"),
    "pepperoni": ("🍕", ["🌶️", "🧀", "🍅"], "#F4B3A0"),
    "four_cheese": ("🧀", ["🧀", "🌿", "🫒"], "#F8DE9C"),
    "bbq": ("🍕", ["🥓", "🧅", "🍗"], "#E8B48E"),
    "fries": ("🍟", ["🧂", "🥫", "🥔"], "#F9DC8B"),
    "wings": ("🍗", ["🍯", "🌶️", "🧄"], "#F2BC92"),
    "garlic_bread": ("🥖", ["🧄", "🌿", "🧈"], "#EED7AE"),
    "lemonade": ("🍋", ["🌿", "🧊", "🍋"], "#CBE8A8"),
    "mors": ("🍒", ["🧊", "🍒", "🌿"], "#F2B0C0"),
    "cappuccino": ("☕", ["🫘", "🥛", "🍪"], "#E3C6A8"),
    "cheesecake": ("🍰", ["🍓", "🫐", "🍓"], "#F6C8D6"),
    "tiramisu": ("🍮", ["☕", "🍫", "🫘"], "#E6CBAE"),
}


def make_dish(name: str, main: str, extras: list[str], color: str) -> None:
    bg = hex_rgb(color)
    img = radial_background(mix(bg, (255, 255, 255), 0.45), mix(bg, INK, 0.08)).convert("RGBA")
    cx, cy = W // 2, H // 2 + 10

    # тарелка: мягкая тень, белый обод, кремовая середина
    plate = 560
    rim = circle(plate, (255, 255, 255))
    paste_with_shadow(img, rim, (cx - plate // 2, cy - plate // 2), blur=30, offset=(0, 26), opacity=80)
    inner = circle(plate - 70, mix(bg, (255, 255, 255), 0.82))
    img.alpha_composite(inner, (cx - (plate - 70) // 2, cy - (plate - 70) // 2))

    scatter(img, extras, seed=hash(name) % 10_000, area=(40, 40, W - 40, H - 40), count=9, size=(70, 120),
            keep_out=(cx, cy, plate // 2 + 20))

    hero = emoji(main, 400, angle=-8)
    paste_with_shadow(img, hero, (cx - hero.width // 2, cy - hero.height // 2), blur=22, offset=(8, 22), opacity=95)

    MENU_OUT.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(MENU_OUT / f"{name}.jpg", quality=88, optimize=True)


# ---------------------------------------------------------------------------
# Баннеры экранов
# ---------------------------------------------------------------------------

def make_banner(name: str, *, title: str, subtitle: str, color: str, hero: str, extras: list[str],
                chips: list[str] = (), dark_text: bool = False, cluster: list[str] | None = None) -> None:
    base = hex_rgb(color)
    img = radial_background(mix(base, (255, 255, 255), 0.18), mix(base, INK, 0.28)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    text_color = INK if dark_text else (255, 255, 255)
    sub_color = mix(text_color, base, 0.25)

    # правая часть: большой круг-подложка и главный объект
    hx, hy, r = int(W * 0.77), int(H * 0.5), 285
    glow = circle(r * 2, (255, 255, 255), 46)
    img.alpha_composite(glow, (hx - r, hy - r))
    glow2 = circle(int(r * 1.6), (255, 255, 255), 40)
    img.alpha_composite(glow2, (hx - int(r * 0.8), hy - int(r * 0.8)))
    scatter(img, extras, seed=hash(name) % 10_000, area=(W // 2 - 20, 20, W - 20, H - 20), count=7, size=(64, 104),
            keep_out=(hx, hy, int(r * 0.85)))
    if cluster:
        positions = [(-130, -110), (130, -110), (-130, 120), (130, 120)]
        for (dx, dy), char in zip(positions, cluster, strict=False):
            sprite = emoji(char, 210, angle=random.Random(char).uniform(-12, 12))
            paste_with_shadow(img, sprite, (hx + dx - sprite.width // 2, hy + dy - sprite.height // 2),
                              blur=16, offset=(4, 14), opacity=90)
    else:
        sprite = emoji(hero, 380, angle=-8)
        paste_with_shadow(img, sprite, (hx - sprite.width // 2, hy - sprite.height // 2), blur=22, offset=(8, 22),
                          opacity=100)

    # левая часть: заголовок, подзаголовок, «чипсы»
    left, max_w = 80, 560
    title_font = font("black", 124)
    title_lines = wrap(draw, title, title_font, max_w)
    if any(draw.textlength(line, font=title_font) > max_w for line in title_lines):
        title_font = fit_font(draw, max(title_lines, key=len), "black", 124, max_w)
    sub_font = font("regular", 46)
    sub_lines = wrap(draw, subtitle, sub_font, max_w)
    chip_font = font("bold", 34)
    block_h = len(title_lines) * int(title_font.size * 1.08) + 18 + len(sub_lines) * 60 + (90 if chips else 0)
    y = (H - block_h) // 2
    for line in title_lines:
        draw.text((left, y), line, font=title_font, fill=text_color)
        y += int(title_font.size * 1.08)
    y += 34
    for line in sub_lines:
        draw.text((left, y), line, font=sub_font, fill=sub_color)
        y += 60
    if chips:
        y += 30
        x = left
        chip_fill = (*mix(base, INK, 0.45), 255) if not dark_text else (255, 255, 255, 200)
        for chip in chips:
            x += rounded_pill(draw, (x, y), chip, chip_font, chip_fill, text_color) + 14

    BANNER_OUT.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(BANNER_OUT / f"{name}.jpg", quality=88, optimize=True)


def banners() -> dict[str, dict]:
    from database.demo_data import CATEGORIES

    dishes = sum(len(c["items"]) for c in CATEGORIES)
    modes = []
    if config.ENABLE_DELIVERY:
        modes.append("Доставка")
    if config.ENABLE_PICKUP:
        modes.append("С собой")
    if config.ENABLE_TABLE or config.ENABLE_BOOKING:
        modes.append("В зале")
    category_style = {
        "Пицца": ("#E8572F", "🍕", ["🍅", "🧀", "🌿", "🫒"]),
        "Закуски": ("#F0A21C", "🍟", ["🍗", "🧄", "🥖", "🧂"]),
        "Напитки": ("#1E9E92", "🥤", ["🍋", "🧊", "☕", "🍒"]),
        "Десерты": ("#D9628F", "🍰", ["🍓", "🍮", "🫐", "🍫"]),
    }
    result = {
        "home": dict(title=config.VENUE_NAME, subtitle="Горячая пицца из печи",
                     color="#E5432F", hero="🍕", extras=["🍅", "🧀", "🌿", "🫒"], chips=modes),
        "closed": dict(title="Мы закрыты", subtitle="Закажите заранее — приготовим к открытию",
                       color="#2B2F4A", hero="🌙", extras=["⭐", "✨"]),
        "menu": dict(title="Меню", subtitle=f"{dishes} блюд — готовим при вас",
                     color="#26211E", hero="🍕", extras=["🌿", "🍅", "🧀"],
                     cluster=[category_style[c["title"]][1] for c in CATEGORIES][:4]),
        "cart": dict(title="Корзина", subtitle="Ещё пара касаний — и готово", color="#2E9E5B", hero="🛒",
                     extras=["🍕", "🥤", "🍟"]),
        "checkout": dict(title="Оформление", subtitle="Пара шагов — и заказ у нас", color="#3550B8", hero="📝",
                         extras=["🍕", "🕐", "📍"]),
        "done": dict(title="Заказ принят!", subtitle="Сообщим о каждом шаге", color="#2E9E5B",
                     hero="🎉", extras=["🍕", "✨", "🛵"]),
        "orders": dict(title="Мои заказы", subtitle="Повтор любимого — в одно касание", color="#5B4BDB",
                       hero="📦", extras=["🍕", "🔁", "🥤"]),
        "booking": dict(title="Бронь столика", subtitle="Подтвердим за пару минут",
                        color="#8C2F39", hero="🍷", extras=["🕯️", "🌹", "✨"]),
        "contacts": dict(title="Как нас найти", subtitle=config.VENUE_ADDRESS, color="#26211E", hero="📍",
                         extras=["🗺️", "🕐", "📞"]),
    }
    # cat_<id>: в свежей базе id категорий идут по порядку из demo_data, начиная с 1
    for index, category in enumerate(CATEGORIES, 1):
        color, hero, extras = category_style.get(category["title"], ("#E5432F", category["emoji"], ["✨"]))
        n = len(category["items"])
        result[f"cat_{index}"] = dict(title=category["title"], subtitle=f"{n} позиции на выбор",
                                                   color=color, hero=hero, extras=extras)
    return result


def main() -> None:
    for name, (main_emoji, extras, color) in DISHES.items():
        make_dish(name, main_emoji, extras, color)
        print(f"+ menu/{name}.jpg")
    for name, spec in banners().items():
        make_banner(name, **spec)
        print(f"+ banners/{name}.jpg")


if __name__ == "__main__":
    main()
