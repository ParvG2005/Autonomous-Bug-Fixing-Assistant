"""Task 12 acceptance: POST /jobs/{id}/publish — gated draft-PR publish from UI.

Runs the FastAPI app over an in-process ASGI transport against a SQLite DB,
with a fake arq pool standing in for the worker queue. No network, no Redis.

The publish route is gated: only an ``approved`` job whose repo has a GitHub
App ``installation_id`` may be published; everything else is a 409 (or 404
for an unknown job). On success it enqueues the ``publish_pr`` worker task.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.api.main import create_app
from app.core.settings import Settings
from app.db.session import Database
from app.models.entities import Job, JobState, Repo
from app.workers.queue import JobQueue
from app.workers.state import transition


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
async def db_and_client(
    tmp_path: Path, fake_pool: _FakePool
) -> AsyncIterator[tuple[httpx.AsyncClient, Database]]:
    settings = Settings(
        app_env="ci",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'publish.db'}",
    )
    app = create_app(settings)
    db = Database.from_settings(settings)
    await db.create_all()
    app.state.db = db  # bypass lifespan; ASGITransport does not run it
    app.state.queue = JobQueue(fake_pool)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        try:
            yield c, db
        finally:
            await db.dispose()


async def _make_job(client: httpx.AsyncClient) -> tuple[str, str]:
    r = await client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]
    r = await client.post("/jobs", json={"repo_id": rid, "body": "x", "title": "t"})
    jid = r.json()["id"]
    return rid, jid


async def _drive_to_approved(
    db: Database, repo_id: str, job_id: str, *, installation_id: int | None
) -> None:
    """Move QUEUED -> RUNNING -> AWAITING_APPROVAL, set installation_id, commit."""
    async with db.session() as s:
        repo = (await s.execute(select(Repo).where(Repo.id == uuid.UUID(repo_id)))).scalar_one()
        repo.installation_id = installation_id
        job = (await s.execute(select(Job).where(Job.id == uuid.UUID(job_id)))).scalar_one()
        transition(job, JobState.RUNNING)
        transition(job, JobState.AWAITING_APPROVAL)
        await s.commit()


async def test_publish_before_approval_is_conflict(
    db_and_client: tuple[httpx.AsyncClient, Database],
) -> None:
    client, _db = db_and_client
    _rid, jid = await _make_job(client)
    r = await client.post(f"/jobs/{jid}/publish")
    assert r.status_code == 409


async def test_publish_unknown_job_is_not_found(
    db_and_client: tuple[httpx.AsyncClient, Database],
) -> None:
    client, _db = db_and_client
    r = await client.post(f"/jobs/{uuid.uuid4()}/publish")
    assert r.status_code == 404


async def test_publish_approved_without_installation_is_conflict(
    db_and_client: tuple[httpx.AsyncClient, Database],
) -> None:
    client, db = db_and_client
    rid, jid = await _make_job(client)
    await _drive_to_approved(db, rid, jid, installation_id=None)
    r = await client.post(f"/jobs/{jid}/approve")
    assert r.status_code == 200
    assert r.json()["state"] == "approved"

    r = await client.post(f"/jobs/{jid}/publish")
    assert r.status_code == 409


async def test_publish_enqueues_when_approved_and_connected(
    db_and_client: tuple[httpx.AsyncClient, Database], fake_pool: _FakePool
) -> None:
    client, db = db_and_client
    rid, jid = await _make_job(client)
    await _drive_to_approved(db, rid, jid, installation_id=999)
    r = await client.post(f"/jobs/{jid}/approve")
    assert r.status_code == 200
    assert r.json()["state"] == "approved"

    r = await client.post(f"/jobs/{jid}/publish")
    assert r.status_code == 202

    assert ("publish_pr", (jid,), f"publish:{jid}") in fake_pool.calls


async def test_job_view_has_capability(
    db_and_client: tuple[httpx.AsyncClient, Database],
) -> None:
    client, _db = db_and_client
    _rid, jid = await _make_job(client)
    r = await client.get(f"/jobs/{jid}")
    j = r.json()
    assert j["repo_full_name"] == "octo/demo"
    assert j["publish_capable"] is False
