"""Сборка всех роутеров бота."""

from aiogram import Router

from . import errors


def setup_routers() -> Router:
    root = Router(name="root")
    root.include_router(errors.router)
    return root
