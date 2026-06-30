"""Discovery API: list findings/scans + promote-to-job (Phase 13), offline."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.api.main import create_app
from app.core.settings import Settings
from app.db.discovery import create_scan, save_finding
from app.db.session import Database
from app.discovery.finding import Candidate
from app.models.entities import (
    FindingSource,
    FindingStatus,
    Job,
    JobState,
    JobTrigger,
    Repo,
)


@pytest.fixture
async def app_db(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Database]]:
    settings = Settings(app_env="ci", database_url=f"sqlite+aiosqlite:///{tmp_path / 'f.db'}")
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


async def _seed_finding(db: Database) -> str:
    async with db.session() as session:
        repo = Repo(gh_repo_id=1, full_name="acme/widgets", installation_id=1)
        session.add(repo)
        await session.flush()
        scan = await create_scan(session, repo.id)
        cand = Candidate(
            source=FindingSource.STATIC,
            summary="None deref on unexercised path",
            rule="mypy:union-attr",
            evidence="app/x.py:12: error: Item 'None' has no attribute 'y'",
            path="app/x.py",
            line=12,
        )
        finding = await save_finding(session, scan, cand, status=FindingStatus.CANDIDATE)
        return str(finding.id)


async def test_list_findings_and_scans(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, db = app_db
    fid = await _seed_finding(db)

    findings = (await client.get("/findings")).json()
    assert len(findings) == 1
    assert findings[0]["id"] == fid
    assert findings[0]["status"] == "candidate"
    assert findings[0]["source"] == "static"

    scans = (await client.get("/scans")).json()
    assert len(scans) == 1
    assert scans[0]["state"] == "done" or scans[0]["state"] == "running"


async def test_promote_finding_files_a_discovery_job(
    app_db: tuple[httpx.AsyncClient, Database],
) -> None:
    client, db = app_db
    fid = await _seed_finding(db)

    resp = await client.post(f"/findings/{fid}/promote")
    assert resp.status_code == 200
    assert resp.json()["status"] == "promoted"

    async with db.session() as session:
        job = (await session.execute(select(Job))).scalar_one()
        assert job.trigger is JobTrigger.DISCOVERY
        assert job.state is JobState.QUEUED
        assert job.finding_id is not None


async def test_promote_unknown_finding_404(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, _ = app_db
    import uuid

    resp = await client.post(f"/findings/{uuid.uuid4()}/promote")
    assert resp.status_code == 404
