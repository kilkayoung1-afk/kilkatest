"""aiogram handlers for the parent bot."""

from aiogram import Dispatcher

from bothost.handlers import admin, code, manage, payment, start


def register(dp: Dispatcher) -> None:
    """Register every router on the dispatcher in priority order."""
    dp.include_router(admin.router)
    dp.include_router(payment.router)
    dp.include_router(manage.router)
    dp.include_router(code.router)
    dp.include_router(start.router)
