"""Подключение к БД через SQLAlchemy async."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from telegram_bot_constructor.db.models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> None:
    """Инициализирует движок и фабрику сессий. Вызывать однократно при старте."""
    global _engine, _session_factory
    _engine = create_async_engine(database_url, future=True, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def create_all() -> None:
    """Создаёт все таблицы (idempotent). Используется при первом запуске."""
    if _engine is None:
        raise RuntimeError("init_engine не вызван")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("init_engine не вызван")
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Контекстный менеджер с авто-commit/rollback."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
