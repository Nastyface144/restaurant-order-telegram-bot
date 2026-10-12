"""Сборка всех роутеров бота. Порядок важен: fallback — последним."""

from aiogram import Router

from . import cart, checkout, errors, fallback, menu, payment, start
from .middlewares import UserMiddleware


def setup_routers() -> Router:
    root = Router(name="root")
    user_mw = UserMiddleware()
    root.message.outer_middleware(user_mw)
    root.callback_query.outer_middleware(user_mw)

    root.include_routers(
        errors.router,
        start.router,
        menu.router,
        payment.router,  # раньше checkout: оплата может прийти посреди нового оформления
        cart.router,
        checkout.router,
        fallback.router,
    )
    return root
