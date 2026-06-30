"""FastAPI dependencies — settings and a per-request DB session.

The :class:`~app.db.session.Database` is created once at app startup and stashed
on ``app.state``; these helpers expose it to route handlers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.db.session import Database


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


async def get_session(db: Database = Depends(get_db)) -> AsyncIterator[AsyncSession]:
    """Yield a transactional session (commit on success, rollback on error)."""
    async with db.session() as session:
        yield session


def settings_dep(request: Request) -> Settings:
    """The settings bound to this app instance (injectable in tests)."""
    settings: Settings = request.app.state.settings
    return settings
