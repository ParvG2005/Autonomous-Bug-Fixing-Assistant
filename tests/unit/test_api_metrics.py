"""GET /metrics — fleet aggregates over finished jobs, over ASGI + SQLite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.api.main import create_app
from app.core.settings import Settings
from app.db.session import Database
from app.models.entities import Fix, Job, JobState, Repo


@pytest.fixture
async def app_db(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Database]]:
    settings = Settings(app_env="ci", database_url=f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
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


_n = 0


async def _seed_finished_job(
    db: Database, *, resolved: bool, edited: bool, cost_usd: float
) -> None:
    global _n
    _n += 1
    async with db.session() as session:
        repo = Repo(gh_repo_id=_n, full_name=f"acme/r{_n}", installation_id=1)
        session.add(repo)
        await session.flush()
        job = Job(
            repo_id=repo.id,
            gh_issue_number=_n,
            state=JobState.AWAITING_APPROVAL if resolved else JobState.FAILED,
            cost={"cost_usd": cost_usd, "input_tokens": 10, "output_tokens": 5},
        )
        session.add(job)
        await session.flush()
        session.add(
            Fix(
                job_id=job.id,
                diff_lines_added=3 if edited else 0,
                diff_lines_removed=1 if edited else 0,
                tests_pass=resolved,
            )
        )


async def test_metrics_aggregates_resolve_rate_and_cost(
    app_db: tuple[httpx.AsyncClient, Database],
) -> None:
    client, db = app_db
    await _seed_finished_job(db, resolved=True, edited=True, cost_usd=2.0)
    await _seed_finished_job(db, resolved=False, edited=True, cost_usd=4.0)

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["resolved"] == 1
    assert body["resolve_rate"] == pytest.approx(0.5)
    assert body["regression_rate"] == pytest.approx(0.5)
    assert body["total_cost_usd"] == pytest.approx(6.0)
    assert body["cost_per_fix_usd"] == pytest.approx(6.0)


async def test_metrics_empty_is_zero(app_db: tuple[httpx.AsyncClient, Database]) -> None:
    client, _ = app_db
    body = (await client.get("/metrics")).json()
    assert body["total"] == 0
    assert body["resolve_rate"] == 0.0
