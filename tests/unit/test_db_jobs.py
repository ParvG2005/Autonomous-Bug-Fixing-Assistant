"""Job ingestion service against a real (SQLite) async DB (Phase 6)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.jobs import IssueRef, ingest_labeled_issue
from app.db.session import Database
from app.models.entities import Artifact, ArtifactKind, Job, JobState, Repo


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


def _ref(issue: int = 7, body: str = "boom") -> IssueRef:
    return IssueRef(
        gh_repo_id=123,
        full_name="acme/widgets",
        installation_id=999,
        gh_issue_number=issue,
        issue_title="Bug: it breaks",
        issue_body=body,
        default_branch="main",
    )


async def test_ingest_creates_queued_job_repo_and_issue_artifact(db: Database) -> None:
    async with db.session() as session:
        result = await ingest_labeled_issue(session, _ref(body="kaboom"))

    assert result.created is True
    assert result.job.state == JobState.QUEUED
    assert result.job.gh_issue_number == 7

    async with db.session() as session:
        repos = (await session.execute(select(Repo))).scalars().all()
        assert len(repos) == 1 and repos[0].full_name == "acme/widgets"

        artifact = (
            await session.execute(select(Artifact).where(Artifact.kind == ArtifactKind.ISSUE_BODY))
        ).scalar_one()
        assert artifact.content == "kaboom"
        assert artifact.sha256 == hashlib.sha256(b"kaboom").hexdigest()
        assert artifact.job_id == result.job.id

        job = (await session.execute(select(Job))).scalar_one()
        assert job.issue_body_ref == artifact.id  # job points at the artifact, not inline


async def test_ingest_is_idempotent_for_a_live_job(db: Database) -> None:
    async with db.session() as session:
        first = await ingest_labeled_issue(session, _ref())
    async with db.session() as session:
        second = await ingest_labeled_issue(session, _ref())

    assert first.created is True
    assert second.created is False
    assert first.job.id == second.job.id

    async with db.session() as session:
        count = (await session.execute(select(func.count()).select_from(Job))).scalar_one()
        assert count == 1


async def test_ingest_reuses_repo_across_issues(db: Database) -> None:
    async with db.session() as session:
        await ingest_labeled_issue(session, _ref(issue=1))
    async with db.session() as session:
        await ingest_labeled_issue(session, _ref(issue=2))

    async with db.session() as session:
        repo_count = (await session.execute(select(func.count()).select_from(Repo))).scalar_one()
        job_count = (await session.execute(select(func.count()).select_from(Job))).scalar_one()
    assert repo_count == 1
    assert job_count == 2
