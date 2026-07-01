"""Task 8 acceptance: POST /jobs — submit a manual fix job from the UI.

Runs the FastAPI app over an in-process ASGI transport against a SQLite DB,
with a fake arq pool standing in for the worker queue. No network, no Redis.
"""

from __future__ import annotations

import uuid
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
async def db(tmp_path: Path) -> Database:
    settings = Settings(
        app_env="ci",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'manual_jobs.db'}",
    )
    return Database.from_settings(settings)


@pytest.fixture
async def api_client(db: Database, fake_pool: _FakePool) -> AsyncIterator[httpx.AsyncClient]:
    await db.create_all()
    app = create_app(Settings(app_env="ci"))
    app.state.db = db  # bypass lifespan; ASGITransport does not run it
    app.state.queue = JobQueue(fake_pool)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        try:
            yield c
        finally:
            await db.dispose()


async def test_create_manual_job(api_client: httpx.AsyncClient, fake_pool: _FakePool) -> None:
    r = await api_client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]

    r = await api_client.post(
        "/jobs", json={"repo_id": rid, "body": "Traceback...", "title": "boom"}
    )
    assert r.status_code == 201
    job = r.json()
    assert job["state"] == "queued"
    assert ("run_job", (job["id"],), f"job:{job['id']}") in fake_pool.calls


async def test_create_job_unknown_repo(api_client: httpx.AsyncClient) -> None:
    import uuid

    r = await api_client.post("/jobs", json={"repo_id": str(uuid.uuid4()), "body": "x"})
    assert r.status_code == 400


async def test_create_job_empty_body(api_client: httpx.AsyncClient) -> None:
    r = await api_client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]

    r = await api_client.post("/jobs", json={"repo_id": rid, "body": "   "})
    assert r.status_code == 400


async def test_create_job_malformed_repo_id(api_client: httpx.AsyncClient) -> None:
    r = await api_client.post("/jobs", json={"repo_id": "not-a-uuid", "body": "x"})
    assert r.status_code == 400


async def test_create_job_persists_ref_and_pr(api_client: httpx.AsyncClient, db: Database) -> None:
    r = await api_client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]

    r = await api_client.post(
        "/jobs",
        json={"repo_id": rid, "body": "boom", "ref": "feature/x", "pr_number": 12},
    )
    assert r.status_code == 201
    job_id = r.json()["id"]

    from sqlalchemy import select

    from app.models.entities import Job

    async with db.session() as session:
        job = (await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))).scalar_one()
        assert job.ref == "feature/x"
        assert job.pr_number == 12
