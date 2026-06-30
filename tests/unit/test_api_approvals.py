"""Approve/reject + artifact-fetch endpoints (Phase 12), over ASGI + SQLite, offline.

These mutate state, so they live behind the C1 human gate: an approve/reject is
only legal from ``awaiting_approval``, records an immutable :class:`Approval` row,
and drives the job state machine. No remote write happens here (publish stays
behind ``bugfix-pr open --confirm``)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.api.main import create_app
from app.core.settings import Settings
from app.db.session import Database
from app.models.entities import (
    Approval,
    ApprovalDecision,
    Artifact,
    ArtifactKind,
    ArtifactStorage,
    Job,
    JobState,
    Repo,
)


@pytest.fixture
async def app_db(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Database]]:
    settings = Settings(app_env="ci", database_url=f"sqlite+aiosqlite:///{tmp_path / 'j.db'}")
    app = create_app(settings)
    db = Database.from_settings(settings)
    await db.create_all()
    app.state.db = db
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
        repo = Repo(gh_repo_id=_counter, full_name=f"acme/w{_counter}", installation_id=1)
        session.add(repo)
        await session.flush()
        job = Job(repo_id=repo.id, gh_issue_number=7, issue_title="boom", state=state)
        session.add(job)
        await session.flush()
        return str(job.id)


async def _add_artifact(db: Database, job_id: str, kind: ArtifactKind, content: str) -> None:
    async with db.session() as session:
        body = content.encode("utf-8")
        session.add(
            Artifact(
                job_id=uuid.UUID(job_id),
                kind=kind,
                storage=ArtifactStorage.INLINE_SMALL,
                content=content,
                size_bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
            )
        )


# --- approve -------------------------------------------------------------


async def test_approve_records_decision_and_transitions(
    app_db: tuple[httpx.AsyncClient, Database],
) -> None:
    client, db = app_db
    job_id = await _seed(db)

    resp = await client.post(f"/jobs/{job_id}/approve", json={"actor": "parv", "note": "lgtm"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "approved"

    async with db.session() as session:
        rec = (
            await session.execute(select(Approval).where(Approval.job_id == uuid.UUID(job_id)))
        ).scalar_one()
        assert rec.decision is ApprovalDecision.APPROVED
        assert rec.actor == "parv"
        assert rec.actor_source == "dashboard"
        job = (await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))).scalar_one()
        assert job.state is JobState.APPROVED


async def test_reject_records_decision_and_transitions(
    app_db: tuple[httpx.AsyncClient, Database],
) -> None:
    client, db = app_db
    job_id = await _seed(db)

    resp = await client.post(f"/jobs/{job_id}/reject", json={"actor": "parv"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "rejected"

    async with db.session() as session:
        rec = (
            await session.execute(select(Approval).where(Approval.job_id == uuid.UUID(job_id)))
        ).scalar_one()
        assert rec.decision is ApprovalDecision.REJECTED


async def test_approve_defaults_actor(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    job_id = await _seed(db)
    resp = await client.post(f"/jobs/{job_id}/approve")
    assert resp.status_code == 200
    async with db.session() as session:
        rec = (
            await session.execute(select(Approval).where(Approval.job_id == uuid.UUID(job_id)))
        ).scalar_one()
        assert rec.actor == "dashboard"


async def test_approve_wrong_state_409(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    job_id = await _seed(db, state=JobState.RUNNING)
    resp = await client.post(f"/jobs/{job_id}/approve")
    assert resp.status_code == 409
    # no spurious approval row written
    async with db.session() as session:
        rows = (
            (await session.execute(select(Approval).where(Approval.job_id == uuid.UUID(job_id))))
            .scalars()
            .all()
        )
        assert rows == []


async def test_approve_twice_409(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    job_id = await _seed(db)
    assert (await client.post(f"/jobs/{job_id}/approve")).status_code == 200
    assert (await client.post(f"/jobs/{job_id}/approve")).status_code == 409


async def test_approve_unknown_job_404(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, _ = app_db
    resp = await client.post(f"/jobs/{uuid.uuid4()}/approve")
    assert resp.status_code == 404


async def test_approve_malformed_id_400(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, _ = app_db
    resp = await client.post("/jobs/not-a-uuid/approve")
    assert resp.status_code == 400


# --- artifact fetch ------------------------------------------------------


async def test_get_diff_artifact(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    job_id = await _seed(db)
    await _add_artifact(db, job_id, ArtifactKind.DIFF, "--- a/x\n+++ b/x\n")

    resp = await client.get(f"/jobs/{job_id}/artifacts/diff")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "diff"
    assert body["content"].startswith("--- a/x")


async def test_get_reasoning_artifact(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    job_id = await _seed(db)
    await _add_artifact(db, job_id, ArtifactKind.REASONING, "# Root cause\nfoo")
    resp = await client.get(f"/jobs/{job_id}/artifacts/reasoning")
    assert resp.status_code == 200
    assert "Root cause" in resp.json()["content"]


async def test_get_missing_artifact_404(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    job_id = await _seed(db)
    resp = await client.get(f"/jobs/{job_id}/artifacts/diff")
    assert resp.status_code == 404


async def test_get_disallowed_artifact_kind_400(
    app_db: tuple[httpx.AsyncClient, Database],
) -> None:
    client, db = app_db
    job_id = await _seed(db)
    # `log` artifacts are streamed via SSE, not fetchable here; `issue_body` is untrusted.
    resp = await client.get(f"/jobs/{job_id}/artifacts/issue_body")
    assert resp.status_code == 400
