"""Ссылки для QR-кодов на столах.

    python tools/table_links.py my_pizza_bot

Печатает ссылки вида https://t.me/my_pizza_bot?start=table_5 для всех столов
из config.TABLES_COUNT. Если установлен пакет qrcode (pip install "qrcode[pil]"),
дополнительно сохраняет PNG-картинки в data/qr/.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from orders.table import table_link  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    username = sys.argv[1].lstrip("@")
    links = {n: table_link(username, n) for n in range(1, config.TABLES_COUNT + 1)}
    for n, link in links.items():
        print(f"Стол {n:>2}: {link}")

    try:
        import qrcode
    except ImportError:
        print('\nДля PNG с QR-кодами установите: pip install "qrcode[pil]"')
        return
    out = ROOT / "data" / "qr"
    out.mkdir(parents=True, exist_ok=True)
    for n, link in links.items():
        qrcode.make(link).save(out / f"table_{n}.png")
    print(f"\nQR-коды сохранены в {out}")


if __name__ == "__main__":
    main()
