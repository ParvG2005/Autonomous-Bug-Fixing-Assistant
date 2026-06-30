"""FastAPI application factory (Phase 6).

The trusted control plane: health, and the GitHub webhook that turns a labeled
issue into a queued job. No agent or remote-write logic lives here — handlers
validate, enqueue, and return. Workers (Phase 7) drain the queue.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.webhooks import router as webhooks_router
from app.core.settings import Settings, get_settings
from app.db.session import Database
from app.telemetry.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database on startup, dispose it on shutdown."""
    settings: Settings = app.state.settings
    app.state.db = Database.from_settings(settings)
    try:
        yield
    finally:
        await app.state.db.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Pass ``settings`` in tests to inject a test DB URL."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Bugfix Assistant API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(webhooks_router)
    return app


app = create_app()


def run() -> None:
    """Console-script entry point: serve with uvicorn."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
