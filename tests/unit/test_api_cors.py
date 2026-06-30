"""CORS for the dashboard dev server (Phase 12).

The Vite dev server runs on a different origin (``localhost:5173``) than the API,
so the browser needs CORS to call ``/jobs``. In production the built assets are
served same-origin, so this only matters for development."""

from __future__ import annotations

import httpx
import pytest

from app.api.main import create_app
from app.core.settings import Settings


@pytest.fixture
def client() -> httpx.AsyncClient:
    app = create_app(Settings(app_env="ci", database_url="sqlite+aiosqlite:///:memory:"))
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_allowed_dev_origin_gets_cors_header(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get("/healthz", headers={"origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


async def test_unknown_origin_is_not_allowed(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get("/healthz", headers={"origin": "http://evil.example"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") != "http://evil.example"
