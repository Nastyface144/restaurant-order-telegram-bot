"""Меню: категории → блюда → карточка блюда с размерами и добавками."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile

import config
from database import cart, menu
from database.models import MenuItem
from keyboards import menu as kb
from keyboards.callbacks import CategoryCb, ItemCb, Nav
from utils import screen
from utils.format import esc, money, truncate

logger = logging.getLogger(__name__)
router = Router(name="menu")
router.callback_query.filter(F.message.chat.type == "private")


def item_picture(item: MenuItem, use_cache: bool = True) -> screen.Picture | None:
    """file_id из кэша → URL → локальный файл из assets/."""
    key = f"item:{item.id}"
    if use_cache and item.photo_file_id:
        return screen.Picture(key, item.photo_file_id)
    if not item.photo:
        return None
    if item.photo.startswith(("http://", "https://")):
        return screen.Picture(key, item.photo)
    path = Path(item.photo)
    if not path.is_absolute():
        path = config.BASE_DIR / path
    if path.is_file():
        return screen.Picture(key, FSInputFile(path))
    if "/" not in item.photo and "." not in item.photo:
        return screen.Picture(key, item.photo)  # похоже на file_id, указанный вручную
    logger.warning("Фото блюда %s не найдено: %s", item.id, item.photo)
    return None


async def show_categories(bot: Bot, callback: CallbackQuery) -> None:
    categories = await menu.get_categories()
    count, total = await cart.cart_summary(callback.from_user.id)
    if categories:
        text = "<b>Меню</b>\nЧто будем заказывать? 👇"
    else:
        text = "<b>Меню</b>\nСейчас всё раскупили 😔 Загляните чуть позже!"
    await screen.show(bot, callback.message.chat.id, text, kb.categories(categories, count, total),
                      picture=screen.banner("menu"), message=callback.message)


@router.callback_query(Nav.filter(F.to == "menu"))
async def on_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()  # ушли из оформления/брони через другую кнопку — ввод больше не ждём
    await show_categories(bot, callback)
    await callback.answer()


@router.callback_query(CategoryCb.filter())
async def on_category(callback: CallbackQuery, callback_data: CategoryCb, bot: Bot) -> None:
    category = await menu.get_category(callback_data.id)
    items = await menu.get_items(callback_data.id) if category else []
    if not category or not items:
        await callback.answer("В этой категории сейчас ничего нет", show_alert=True)
        await show_categories(bot, callback)
        return
    count, total = await cart.cart_summary(callback.from_user.id)
    # Подпись — как строчки в бумажном меню: название, цена и пара слов о составе
    rows = [f"<b>{esc(category.title)}</b>", ""]
    for item in items[:kb.ITEMS_PER_PAGE]:
        rows.append(f"<b>{esc(item.title)}</b> · {kb.price_from(item)}")
        rows.append(f"<i>{esc(truncate(item.description.split('. ')[0], 60))}</i>")
    rows += ["", "Нажмите на блюдо — покажем фото и состав 👇"]
    await screen.show(
        bot, callback.message.chat.id, "\n".join(rows),
        kb.category_items(category, items, callback_data.page, count, total),
        picture=screen.banner(f"cat_{category.id}") or screen.banner("menu"),
        message=callback.message,
    )
    await callback.answer()


def item_caption(item: MenuItem, size_code: str, addon_codes: list[str], qty: int) -> str:
    lines = [f"<b>{esc(item.title)}</b>", esc(item.description), ""]
    unit = item.unit_price(size_code, addon_codes)
    details = []
    size = item.get_size(size_code)
    if size and len(item.sizes) > 1:
        details.append(esc(size.title))
    addons = item.get_addons(addon_codes)
    if addons:
        details.append("+ " + ", ".join(esc(a.title.lower()) for a in addons))
    detail = " ".join(details)
    if qty > 1:
        price = f"💰 <b>{money(unit * qty)}</b> · {qty} × {money(unit)}"
    else:
        price = f"💰 <b>{money(unit)}</b>"
    lines.append(price + (f" · {detail}" if detail else ""))
    return "\n".join(lines)


async def render_item(bot: Bot, callback: CallbackQuery, item: MenuItem, data: ItemCb) -> None:
    size = item.get_size(data.s) or item.default_size
    size_code = size.code if size else ""
    mask = data.m & ((1 << len(item.addons)) - 1)
    addon_codes = item.addon_codes_from_mask(mask)
    qty = min(max(data.q, 1), cart.MAX_QTY)

    text = item_caption(item, size_code, addon_codes, qty)
    count, total = await cart.cart_summary(callback.from_user.id)
    keyboard = kb.item_card(item, size_code, mask, qty, data.p, count, total)

    # Та же картинка уже на экране (сменили размер/добавку) — screen.show поменяет только подпись
    picture = item_picture(item)
    chat_id = callback.message.chat.id
    try:
        sent = await screen.show(bot, chat_id, text, keyboard, picture=picture, message=callback.message)
    except TelegramBadRequest as exc:
        if picture is None or not item.photo_file_id:
            raise
        # Кэшированный file_id устарел (например, сменили токен бота) — грузим заново
        logger.info("file_id фото блюда %s недействителен (%s), загружаем заново", item.id, exc)
        picture = item_picture(item, use_cache=False)
        sent = await screen.show(bot, chat_id, text, keyboard, picture=picture, message=callback.message)

    if sent and sent.photo and picture and not isinstance(picture.source, str):
        await menu.save_photo_file_id(item.id, sent.photo[-1].file_id)


@router.callback_query(ItemCb.filter(F.a == "n"))
async def on_item_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(ItemCb.filter(F.a == "v"))
async def on_item(callback: CallbackQuery, callback_data: ItemCb, bot: Bot) -> None:
    item = await menu.get_item(callback_data.id)
    if item is None or not item.is_available:
        await callback.answer("😔 Это блюдо сейчас недоступно", show_alert=True)
        await show_categories(bot, callback)
        return
    await render_item(bot, callback, item, callback_data)
    await callback.answer()


@router.callback_query(ItemCb.filter(F.a == "add"))
async def on_add_to_cart(callback: CallbackQuery, callback_data: ItemCb, bot: Bot) -> None:
    if not config.FEATURES.ordering:
        await callback.answer()
        return
    item = await menu.get_item(callback_data.id)
    if item is None or not item.is_available:
        await callback.answer("😔 Это блюдо только что закончилось", show_alert=True)
        await show_categories(bot, callback)
        return

    size = item.get_size(callback_data.s) or item.default_size
    size_code = size.code if size else ""
    addon_codes = item.addon_codes_from_mask(callback_data.m)
    qty = min(max(callback_data.q, 1), cart.MAX_QTY)
    await cart.add_to_cart(callback.from_user.id, item.id, size_code, addon_codes, qty)

    title = item.title + (f", {size.title}" if size and len(item.sizes) > 1 else "")
    count, total = await cart.cart_summary(callback.from_user.id)
    await callback.answer(f"✅ {title} × {qty} — в корзине.\nВсего: {money(total)}")
    # Сбрасываем количество на 1 и обновляем сумму на кнопке корзины
    reset = ItemCb(id=item.id, s=size_code, m=callback_data.m, q=1, p=callback_data.p)
    await render_item(bot, callback, item, reset)
