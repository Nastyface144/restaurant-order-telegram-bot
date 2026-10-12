"""Сборка всех роутеров бота. Порядок важен: fallback — последним."""

from aiogram import Router

from . import cart, errors, fallback, menu, start
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
        cart.router,
        fallback.router,
    )
    return root
