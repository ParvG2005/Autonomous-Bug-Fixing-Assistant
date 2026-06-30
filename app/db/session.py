"""Async engine + session factory.

A single process-wide engine is created lazily from ``Settings.database_url``.
``create_all`` is provided for tests and local bootstrap; production schema is
owned by Alembic (see ``migrations/``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings, get_settings
from app.models.base import Base


def _normalize_async_url(url: str) -> str:
    """Coerce common sync URLs to their async drivers.

    The ``.env`` ships ``postgresql+psycopg://`` which psycopg3 serves async too,
    so it is already fine. A bare ``postgresql://`` or ``sqlite://`` is upgraded.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


class Database:
    """Owns one async engine + sessionmaker for the process."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(_normalize_async_url(url), echo=echo)
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Database:
        settings = settings or get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured")
        return cls(settings.database_url, echo=settings.db_echo)

    async def create_all(self) -> None:
        """Create every table (tests / local bootstrap; prod uses Alembic)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A session scope that commits on success and rolls back on error."""
        async with self.sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
