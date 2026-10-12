"""/admin: сводка за день, заказы и брони за сегодня, стоп-лист, рассылка."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

import config
from database import menu, users
from database.models import OrderStatus
from keyboards import admin as kb
from keyboards.callbacks import AdminCb
from orders.booking import STATUS_LABELS as BOOKING_LABELS
from orders.booking import guests_text
from orders.checkout import METHOD_TITLES
from orders.statuses import status_label
from utils import screen
from utils.format import esc, money, plural
from utils.timeutil import human_date, now_local

from . import stats as stats_mod
from .broadcast import BroadcastResult, broadcast

logger = logging.getLogger(__name__)
router = Router(name="admin")

LIST_LIMIT = 30
_running_broadcasts: set[asyncio.Task] = set()


def is_admin(event: TelegramObject) -> bool:
    user = getattr(event, "from_user", None)
    return user is not None and user.id in config.ADMIN_IDS


router.message.filter(F.chat.type == "private", is_admin)
router.callback_query.filter(F.message.chat.type == "private", is_admin)


class AdminForm(StatesGroup):
    broadcast = State()


# ---------------------------------------------------------------------------
# Сводка
# ---------------------------------------------------------------------------

def dashboard_text(s: stats_mod.DayStats) -> str:
    by_status = s.by_status
    lines = [f"⚙️ <b>Админ-панель</b> · {human_date(s.day)}, {s.day:%d.%m}", ""]
    lines.append(f"🧾 Заказов: <b>{len(s.orders)}</b>")
    if s.orders:
        lines.append(
            f"    в работе {len(s.in_progress)} · выполнено {len(s.completed)} · "
            f"отклонено {by_status[OrderStatus.REJECTED] + by_status[OrderStatus.CANCELLED]}"
        )
    lines.append(f"💰 Выручка: <b>{money(s.revenue)}</b>")
    if s.completed:
        lines.append(f"    средний чек {money(s.average_check)}")
    if s.expected_revenue:
        lines.append(f"    ещё в работе на {money(s.expected_revenue)}")
    lines.append(f"📅 Броней: <b>{len(s.bookings)}</b>"
                 + (f" · ждут подтверждения {s.pending_bookings}" if s.pending_bookings else ""))
    if s.guests_expected:
        lines.append(f"    ожидаем {guests_text(s.guests_expected)}")
    lines.append(f"🚫 В стоп-листе: {s.stopped_items} {plural(s.stopped_items, 'блюдо', 'блюда', 'блюд')}")
    lines.append(f"👥 Клиентов в боте: {s.users_active}")
    return "\n".join(lines)


async def show_dashboard(bot: Bot, chat_id: int, message: Message | None = None, force_new: bool = False) -> None:
    data = await stats_mod.collect(now_local().date())
    await screen.show(bot, chat_id, dashboard_text(data), kb.dashboard(), message=message, force_new=force_new)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await show_dashboard(bot, message.chat.id, force_new=True)
    await screen.delete_user_input(message)


@router.callback_query(AdminCb.filter(F.a == "home"))
async def on_home(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await show_dashboard(bot, callback.message.chat.id, message=callback.message)
    await callback.answer()


@router.callback_query(AdminCb.filter(F.a == "orders"))
async def on_orders_today(callback: CallbackQuery, bot: Bot) -> None:
    data = await stats_mod.collect(now_local().date())
    orders = list(reversed(data.orders))  # свежие сверху
    lines = [f"🧾 <b>Заказы за сегодня</b> · {len(orders)}", ""]
    if not orders:
        lines.append("Пока ни одного заказа.")
    for o in orders[:LIST_LIMIT]:
        where = f"стол {o.table_no}" if o.table_no else METHOD_TITLES[o.method].split()[0]
        lines.append(f"<b>№{o.id}</b> {o.created_at:%H:%M} · {where} · {money(o.total)} · "
                     f"{status_label(o.status, o.method)}")
    if len(orders) > LIST_LIMIT:
        lines.append(f"\n…и ещё {len(orders) - LIST_LIMIT}")
    lines += ["", f"💰 Выручка: <b>{money(data.revenue)}</b>"]
    await screen.show(bot, callback.message.chat.id, "\n".join(lines), kb.back_to_dashboard(),
                      message=callback.message)
    await callback.answer()


@router.callback_query(AdminCb.filter(F.a == "bookings"))
async def on_bookings_today(callback: CallbackQuery, bot: Bot) -> None:
    data = await stats_mod.collect(now_local().date())
    lines = [f"📅 <b>Брони на сегодня</b> · {len(data.bookings)}", ""]
    if not data.bookings:
        lines.append("Броней нет.")
    for b in data.bookings[:LIST_LIMIT]:
        lines.append(f"<b>{b.starts_at:%H:%M}</b> · {guests_text(b.guests)} · {esc(b.name)} · "
                     f"{BOOKING_LABELS[b.status]}")
    if data.pending_bookings:
        lines += ["", "Подтвердить заявки можно в карточках брони выше в этом чате."]
    await screen.show(bot, callback.message.chat.id, "\n".join(lines), kb.back_to_dashboard(),
                      message=callback.message)
    await callback.answer()


# ---------------------------------------------------------------------------
# Стоп-лист
# ---------------------------------------------------------------------------

async def show_stop_categories(bot: Bot, callback: CallbackQuery) -> None:
    categories = await menu.get_categories(only_with_available=False)
    stopped = await menu.count_stopped_by_category()
    text = ("🚫 <b>Стоп-лист</b>\n\nБлюда из стоп-листа скрыты из меню и не попадут в заказ.\n"
            "Выберите категорию 👇")
    await screen.show(bot, callback.message.chat.id, text, kb.stop_categories(categories, stopped),
                      message=callback.message)


async def show_stop_items(bot: Bot, callback: CallbackQuery, category_id: int) -> None:
    category = await menu.get_category(category_id)
    if category is None:
        await show_stop_categories(bot, callback)
        return
    items = await menu.get_items(category_id, only_available=False)
    text = (f"🚫 <b>Стоп-лист · {esc(category.title)}</b>\n\n"
            "✅ — в продаже, 🚫 — скрыто. Нажмите на блюдо, чтобы переключить.")
    await screen.show(bot, callback.message.chat.id, text, kb.stop_items(category, items), message=callback.message)


@router.callback_query(AdminCb.filter(F.a == "stop"))
async def on_stop_list(callback: CallbackQuery, bot: Bot) -> None:
    await show_stop_categories(bot, callback)
    await callback.answer()


@router.callback_query(AdminCb.filter(F.a == "stopcat"))
async def on_stop_category(callback: CallbackQuery, callback_data: AdminCb, bot: Bot) -> None:
    await show_stop_items(bot, callback, callback_data.v)
    await callback.answer()


@router.callback_query(AdminCb.filter(F.a == "toggle"))
async def on_toggle(callback: CallbackQuery, callback_data: AdminCb, bot: Bot) -> None:
    available = await menu.toggle_availability(callback_data.v)
    item = await menu.get_item(callback_data.v)
    if item is None or available is None:
        await callback.answer("Блюдо не найдено", show_alert=True)
        return
    logger.info("Стоп-лист: «%s» → %s (%s)", item.title, "в продаже" if available else "скрыто",
                callback.from_user.full_name)
    await show_stop_items(bot, callback, item.category_id)
    await callback.answer(f"«{item.title}» снова в меню" if available else f"«{item.title}» скрыто из меню")


# ---------------------------------------------------------------------------
# Рассылка
# ---------------------------------------------------------------------------

@router.callback_query(AdminCb.filter(F.a == "bc"))
async def on_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.set_state(AdminForm.broadcast)
    await state.update_data(bc_message=None)
    text = ("📣 <b>Рассылка</b>\n\nПришлите сообщение для клиентов: текст или фото с подписью.\n"
            "Форматирование сохранится. Перед отправкой покажу, сколько человек его получат.")
    await screen.show(bot, callback.message.chat.id, text, kb.broadcast_wait(), message=callback.message)
    await callback.answer()


@router.message(AdminForm.broadcast, ~F.text.startswith("/"))
async def on_broadcast_message(message: Message, state: FSMContext, bot: Bot) -> None:
    if not (message.text or message.photo):
        await screen.show(bot, message.chat.id,
                          "📣 <b>Рассылка</b>\n\n⚠️ Можно отправить только текст или фото с подписью. Попробуйте ещё раз.",
                          kb.broadcast_wait(), force_new=True)
        return
    await state.update_data(bc_message=message.message_id)
    recipients = [u for u in await users.get_active_user_ids() if u != message.from_user.id]
    text = (f"📣 <b>Рассылка</b>\n\nСообщение выше 👆 получат <b>{len(recipients)}</b> "
            f"{plural(len(recipients), 'клиент', 'клиента', 'клиентов')}.\nОтправляем?")
    # Экран — ниже сообщения администратора, чтобы превью было видно над ним
    await screen.show(bot, message.chat.id, text, kb.broadcast_confirm(len(recipients)), force_new=True)


@router.callback_query(AdminCb.filter(F.a == "bc_cancel"))
async def on_broadcast_cancel(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await show_dashboard(bot, callback.message.chat.id, message=callback.message)
    await callback.answer("Рассылка отменена")


@router.callback_query(AdminCb.filter(F.a == "bc_send"))
async def on_broadcast_send(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    message_id = (await state.get_data()).get("bc_message")
    await state.clear()  # повторное нажатие не запустит вторую рассылку
    if not message_id:
        await callback.answer("Сообщение для рассылки не найдено — начните заново", show_alert=True)
        return

    chat_id = callback.message.chat.id
    status_message = callback.message
    await screen.show(bot, chat_id, "📣 Рассылка запущена… ⏳", None, message=status_message)
    await callback.answer("Рассылка запущена")

    async def progress(result: BroadcastResult) -> None:
        done = result.sent + result.blocked + result.failed
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id,
                                        text=f"📣 Рассылка… {done} из {result.total} ⏳")
        except TelegramAPIError:
            pass

    async def run() -> None:
        try:
            result = await broadcast(bot, chat_id, message_id, exclude={callback.from_user.id},
                                     on_progress=progress)
            text = (f"✅ <b>Рассылка завершена</b>\n\nДоставлено: {result.sent} из {result.total}\n"
                    f"Заблокировали бота: {result.blocked}\nОшибки: {result.failed}")
        except Exception:
            logger.exception("Рассылка упала")
            text = "😔 Рассылка прервалась из-за ошибки — подробности в логах."
        try:
            await screen.show(bot, chat_id, text, kb.back_to_dashboard(), message=status_message)
        except TelegramAPIError:
            logger.warning("Не удалось показать итог рассылки")

    # Рассылка идёт в фоне — бот продолжает отвечать клиентам
    task = asyncio.create_task(run())
    _running_broadcasts.add(task)
    task.add_done_callback(_running_broadcasts.discard)
