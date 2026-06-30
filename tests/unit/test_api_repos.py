"""Task 6 acceptance: /repos add/list/delete/connect/scan over the real app.

Runs the FastAPI app over an in-process ASGI transport against a SQLite DB,
with a fake arq pool standing in for the worker queue. No network, no Redis.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.api.main import create_app
from app.core.settings import Settings
from app.db.session import Database
from app.workers.queue import JobQueue


class _FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, str | None]] = []

    async def enqueue_job(self, task, *args, _job_id=None):
        self.calls.append((task, args, _job_id))
        return object()


@pytest.fixture
async def fake_pool() -> _FakePool:
    return _FakePool()


@pytest.fixture
async def api_client(tmp_path: Path, fake_pool: _FakePool) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        app_env="ci",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'repos.db'}",
    )
    app = create_app(settings)
    db = Database.from_settings(settings)
    await db.create_all()
    app.state.db = db  # bypass lifespan; ASGITransport does not run it
    app.state.queue = JobQueue(fake_pool)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        try:
            yield c
        finally:
            await db.dispose()


async def test_add_list_delete_repo(api_client: httpx.AsyncClient) -> None:
    r = await api_client.post("/repos", json={"clone_url": "https://github.com/octo/demo"})
    assert r.status_code == 201
    body = r.json()
    assert body["full_name"] == "octo/demo"
    assert body["publish_capable"] is False

    r = await api_client.get("/repos")
    assert [x["full_name"] for x in r.json()] == ["octo/demo"]

    r = await api_client.delete(f"/repos/{body['id']}")
    assert r.status_code == 204

    r = await api_client.get("/repos")
    assert r.json() == []


async def test_add_repo_bad_url(api_client: httpx.AsyncClient) -> None:
    r = await api_client.post("/repos", json={"clone_url": "not-a-url"})
    assert r.status_code == 400


async def test_scan_enqueues(api_client: httpx.AsyncClient, fake_pool: _FakePool) -> None:
    r = await api_client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]

    r = await api_client.post(f"/repos/{rid}/scan")
    assert r.status_code == 202
    assert ("scan_repo", (rid,), f"scan_repo:{rid}") in fake_pool.calls


async def test_connect_enqueues(api_client: httpx.AsyncClient, fake_pool: _FakePool) -> None:
    r = await api_client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]

    r = await api_client.post(f"/repos/{rid}/connect")
    assert r.status_code == 202
    assert ("connect_repo", (rid,), f"connect_repo:{rid}") in fake_pool.calls
