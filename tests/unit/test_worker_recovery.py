"""Crash recovery (Phase 7): stranded ``running`` jobs are re-queued."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.session import Database
from app.models.entities import Artifact, ArtifactKind, Job, JobState, Repo
from app.workers.recovery import recover_stuck_jobs


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'rec.db'}")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


_counter = 0


async def _seed(db: Database, state: JobState) -> str:
    global _counter
    _counter += 1
    async with db.session() as session:
        repo = Repo(gh_repo_id=_counter, full_name=f"a/b{_counter}", installation_id=1)
        session.add(repo)
        await session.flush()
        job = Job(repo_id=repo.id, gh_issue_number=1, state=state)
        session.add(job)
        await session.flush()
        return str(job.id)


async def test_running_jobs_reset_to_queued_others_untouched(db: Database) -> None:
    running = await _seed(db, JobState.RUNNING)
    awaiting = await _seed(db, JobState.AWAITING_APPROVAL)
    done = await _seed(db, JobState.DONE)

    async with db.session() as session:
        recovered = await recover_stuck_jobs(session)

    assert recovered == [running]
    async with db.session() as session:
        states = {str(j.id): j.state for j in (await session.execute(select(Job))).scalars().all()}
        assert states[running] is JobState.QUEUED
        assert states[awaiting] is JobState.AWAITING_APPROVAL
        assert states[done] is JobState.DONE

        # The recovery left an audit log line on the reclaimed job.
        logs = (
            (
                await session.execute(
                    select(Artifact).where(
                        Artifact.kind == ArtifactKind.LOG, Artifact.job_id == _uuid(running)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any("re-queued" in (a.content or "") for a in logs)


async def test_recovery_is_idempotent(db: Database) -> None:
    await _seed(db, JobState.RUNNING)
    async with db.session() as session:
        first = await recover_stuck_jobs(session)
    async with db.session() as session:
        second = await recover_stuck_jobs(session)
    assert len(first) == 1
    assert second == []


def _uuid(s: str) -> object:
    import uuid

    return uuid.UUID(s)
