"""Dev bootstrap: reset guard + wipe, and scrape via a fake issue source (Phase 14)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.settings import Settings
from app.db.bootstrap import (
    RepoIdentity,
    ResetNotAllowed,
    ScrapedIssue,
    reset_job_tables,
    run_bootstrap,
    scrape_repo,
)
from app.db.jobs import IssueRef, ingest_labeled_issue
from app.db.session import Database
from app.models.entities import Artifact, ArtifactKind, Job, JobState, JobTrigger, Repo


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'boot.db'}")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


def _identity() -> RepoIdentity:
    return RepoIdentity(gh_repo_id=42, full_name="acme/widgets", installation_id=7)


async def _seed_a_job(db: Database) -> None:
    async with db.session() as session:
        await ingest_labeled_issue(
            session,
            IssueRef(
                gh_repo_id=42,
                full_name="acme/widgets",
                installation_id=7,
                gh_issue_number=1,
                issue_title="boom",
                issue_body="kaboom",
            ),
        )


async def test_reset_wipes_jobs_but_keeps_repo(db: Database) -> None:
    await _seed_a_job(db)
    settings = Settings(app_env="local")

    counts = await reset_job_tables(db, app_env=settings.app_env)
    assert counts["job"] == 1

    async with db.session() as session:
        jobs = (await session.execute(select(func.count()).select_from(Job))).scalar_one()
        arts = (await session.execute(select(func.count()).select_from(Artifact))).scalar_one()
        repos = (await session.execute(select(func.count()).select_from(Repo))).scalar_one()
    assert jobs == 0 and arts == 0  # job history wiped
    assert repos == 1  # the install survives


async def test_reset_refuses_outside_local(db: Database) -> None:
    await _seed_a_job(db)
    with pytest.raises(ResetNotAllowed):
        await reset_job_tables(db, app_env="prod")
    # Nothing was deleted.
    async with db.session() as session:
        jobs = (await session.execute(select(func.count()).select_from(Job))).scalar_one()
    assert jobs == 1


async def test_scrape_enqueues_capped_scrape_jobs(db: Database) -> None:
    issues = [ScrapedIssue(number=n, title=f"bug {n}", body=f"body {n}") for n in (1, 2, 3)]
    async with db.session() as session:
        jobs = await scrape_repo(session, _identity(), issues, max_jobs=2)

    assert len(jobs) == 2  # capped
    async with db.session() as session:
        rows = (await session.execute(select(Job))).scalars().all()
        assert all(j.trigger is JobTrigger.SCRAPE for j in rows)
        assert all(j.state is JobState.QUEUED for j in rows)
        # The untrusted body landed in an artifact, not inline.
        arts = (
            (
                await session.execute(
                    select(Artifact).where(Artifact.kind == ArtifactKind.ISSUE_BODY)
                )
            )
            .scalars()
            .all()
        )
        assert {a.content for a in arts} == {"body 1", "body 2"}


async def test_run_bootstrap_resets_then_scrapes(db: Database) -> None:
    await _seed_a_job(db)  # stale job to be wiped
    settings = Settings(app_env="local", scrape_max_jobs=5)

    def source(full_name: str) -> tuple[RepoIdentity, list[ScrapedIssue]]:
        return _identity(), [ScrapedIssue(number=10, title="fresh", body="fresh body")]

    summary = await run_bootstrap(
        db,
        settings,
        reset=True,
        scrape=True,
        repos=["acme/widgets"],
        issue_source=source,
    )

    assert summary["scraped"] == {"acme/widgets": 1}
    async with db.session() as session:
        rows = (await session.execute(select(Job))).scalars().all()
    # Only the freshly scraped job remains (the stale one was wiped first).
    assert len(rows) == 1
    assert rows[0].trigger is JobTrigger.SCRAPE
    assert rows[0].gh_issue_number == 10
