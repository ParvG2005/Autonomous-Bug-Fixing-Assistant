"""Job status + SSE log endpoints (Phase 7), over ASGI + SQLite, offline."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.api.main import create_app
from app.core.settings import Settings
from app.db.session import Database
from app.models.entities import Job, JobState, Repo
from app.workers.progress import record_log


@pytest.fixture
async def app_db(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Database]]:
    settings = Settings(app_env="ci", database_url=f"sqlite+aiosqlite:///{tmp_path / 'j.db'}")
    app = create_app(settings)
    db = Database.from_settings(settings)
    await db.create_all()
    app.state.db = db  # bypass lifespan (ASGITransport does not run it)
    app.state.queue = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        try:
            yield c, db
        finally:
            await db.dispose()


_counter = 0


async def _seed(db: Database, state: JobState = JobState.AWAITING_APPROVAL) -> str:
    global _counter
    _counter += 1
    async with db.session() as session:
        repo = Repo(gh_repo_id=_counter, full_name=f"acme/widgets{_counter}", installation_id=1)
        session.add(repo)
        await session.flush()
        job = Job(repo_id=repo.id, gh_issue_number=7, issue_title="boom", state=state)
        session.add(job)
        await session.flush()
        await record_log(session, job.id, "running: cloning acme/widgets")
        await record_log(session, job.id, "fix verified; awaiting human approval")
        return str(job.id)


async def test_get_job_returns_status(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    job_id = await _seed(db)

    resp = await client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == job_id
    assert body["state"] == "awaiting_approval"
    assert body["gh_issue_number"] == 7


async def test_get_unknown_job_404(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, _ = app_db
    import uuid

    resp = await client.get(f"/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_malformed_job_id_400(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, _ = app_db
    resp = await client.get("/jobs/not-a-uuid")
    assert resp.status_code == 400


async def test_list_jobs(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    await _seed(db)
    await _seed(db, state=JobState.QUEUED)

    resp = await client.get("/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_sse_logs_replay_and_close(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    job_id = await _seed(db)  # awaiting_approval -> stream closes after replay

    async with client.stream("GET", f"/jobs/{job_id}/logs") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = ""
        async for chunk in resp.aiter_text():
            text += chunk

    assert "cloning acme/widgets" in text
    assert "awaiting human approval" in text
    assert "event: state" in text
