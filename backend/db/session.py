"""异步数据库会话: engine + sessionmaker + FastAPI 依赖。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import settings


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def build_engine(database_url: str | None = None, echo: bool | None = None) -> AsyncEngine:
    url = database_url or settings.database_url
    kwargs: dict = {"echo": echo if echo is not None else settings.db_echo}
    if not _is_sqlite(url):
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
        )
    return create_async_engine(url, **kwargs)


engine: AsyncEngine = build_engine()
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖: 每请求一个会话。"""
    async with SessionLocal() as session:
        yield session


async def ping_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False