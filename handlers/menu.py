"""Меню: категории → блюда → карточка блюда с размерами и добавками."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

import config
from database import cart, menu
from database.models import MenuItem
from keyboards import menu as kb
from keyboards.callbacks import CategoryCb, ItemCb, Nav
from utils import screen
from utils.format import esc, money

logger = logging.getLogger(__name__)
router = Router(name="menu")
router.callback_query.filter(F.message.chat.type == "private")

CAPTION_LIMIT = 1024


def _photo_source(item: MenuItem, use_cache: bool = True) -> str | FSInputFile | None:
    """file_id из кэша → URL → локальный файл из assets/."""
    if use_cache and item.photo_file_id:
        return item.photo_file_id
    if not item.photo:
        return None
    if item.photo.startswith(("http://", "https://")):
        return item.photo
    path = Path(item.photo)
    if not path.is_absolute():
        path = config.BASE_DIR / path
    if path.is_file():
        return FSInputFile(path)
    if "/" not in item.photo and "." not in item.photo:
        return item.photo  # похоже на file_id, указанный вручную
    logger.warning("Фото блюда %s не найдено: %s", item.id, item.photo)
    return None


async def show_categories(bot: Bot, callback: CallbackQuery) -> None:
    categories = await menu.get_categories()
    count = await cart.count_cart_items(callback.from_user.id)
    if categories:
        text = "📖 <b>Меню</b>\n\nВыберите категорию 👇"
    else:
        text = "📖 <b>Меню</b>\n\nСейчас всё раскупили 😔 Загляните чуть позже!"
    await screen.show(bot, callback.message.chat.id, text, kb.categories(categories, count), message=callback.message)


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
    count = await cart.count_cart_items(callback.from_user.id)
    text = f"{category.emoji} <b>{esc(category.title)}</b>\n\nВыберите блюдо 👇"
    await screen.show(
        bot, callback.message.chat.id, text,
        kb.category_items(category, items, callback_data.page, count),
        message=callback.message,
    )
    await callback.answer()


def item_caption(item: MenuItem, size_code: str, addon_codes: list[str], qty: int) -> str:
    lines = [f"<b>{esc(item.title)}</b>", esc(item.description)]
    size = item.get_size(size_code)
    details = []
    if size and len(item.sizes) > 1:
        details.append(f"📏 Размер: {esc(size.title)}")
    addons = item.get_addons(addon_codes)
    if addons:
        details.append("➕ Добавки: " + ", ".join(esc(a.title) for a in addons))
    if details:
        lines += ["", *details]

    unit = item.unit_price(size_code, addon_codes)
    price = f"💰 <b>{money(unit)}</b>" if qty == 1 else f"💰 {money(unit)} × {qty} = <b>{money(unit * qty)}</b>"
    lines += ["", price]
    if config.FEATURES.ordering:
        choose = []
        if len(item.sizes) > 1:
            choose.append("размер")
        if item.addons:
            choose.append("добавки")
        if choose:
            lines += ["", f"<i>Выберите {' и '.join(choose)} кнопками ниже</i>"]
    text = "\n".join(lines)
    if len(text) > CAPTION_LIMIT:  # подпись к фото ограничена 1024 символами
        text = text[:CAPTION_LIMIT - 1] + "…"
    return text


async def render_item(bot: Bot, callback: CallbackQuery, item: MenuItem, data: ItemCb, *, only_caption: bool) -> None:
    size = item.get_size(data.s) or item.default_size
    size_code = size.code if size else ""
    mask = data.m & ((1 << len(item.addons)) - 1)
    addon_codes = item.addon_codes_from_mask(mask)
    qty = min(max(data.q, 1), cart.MAX_QTY)

    text = item_caption(item, size_code, addon_codes, qty)
    count = await cart.count_cart_items(callback.from_user.id)
    keyboard = kb.item_card(item, size_code, mask, qty, data.p, count)

    # Меняется только выбор — не перезагружаем фото, правим подпись
    if only_caption and await screen.edit_caption(bot, callback.message, text, keyboard):
        return

    photo = _photo_source(item)
    chat_id = callback.message.chat.id
    try:
        sent = await screen.show(bot, chat_id, text, keyboard, photo=photo, message=callback.message)
    except TelegramBadRequest as exc:
        if photo is None or not item.photo_file_id:
            raise
        # Кэшированный file_id устарел (например, сменили токен бота) — грузим заново
        logger.info("file_id фото блюда %s недействителен (%s), загружаем заново", item.id, exc)
        photo = _photo_source(item, use_cache=False)
        sent = await screen.show(bot, chat_id, text, keyboard, photo=photo, message=callback.message)

    if sent and sent.photo and not isinstance(photo, str):
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
    # Если это уже карточка этого блюда (сменили размер/добавку) — только подпись
    already_open = bool(callback.message.photo) and _is_card_of(callback.message, item.id)
    await render_item(bot, callback, item, callback_data, only_caption=already_open)
    await callback.answer()


def _is_card_of(message: Message, item_id: int) -> bool:
    markup = message.reply_markup
    if not markup:
        return False
    for row in markup.inline_keyboard:
        for button in row:
            data = button.callback_data or ""
            if data.startswith(f"{ItemCb.__prefix__}:{item_id}:"):
                return True
    return False


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
    await callback.answer(f"✅ В корзине: {title} × {qty}")
    # Сбрасываем количество на 1 и обновляем счётчик корзины на кнопке
    reset = ItemCb(id=item.id, s=size_code, m=callback_data.m, q=1, p=callback_data.p)
    await render_item(bot, callback, item, reset, only_caption=True)
