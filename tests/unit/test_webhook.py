"""Phase 6 acceptance: a labeled issue creates a queued job row via webhook.

Runs the real FastAPI app over an in-process ASGI transport against a SQLite DB,
posting GitHub-signed deliveries. No network, no Postgres.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.api.main import create_app
from app.api.security import compute_signature
from app.core.settings import Settings
from app.db.session import Database
from app.models.entities import Job, JobState

SECRET = "webhook-secret"


def _payload(issue: int = 42, label: str = "autofix", action: str = "labeled") -> dict:
    return {
        "action": action,
        "label": {"name": label},
        "repository": {
            "id": 555,
            "full_name": "acme/widgets",
            "default_branch": "main",
            "language": "Python",
        },
        "issue": {"number": issue, "title": "Crash on empty input", "body": "traceback..."},
        "installation": {"id": 9001},
    }


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        app_env="ci",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'wh.db'}",
        github_webhook_secret=SecretStr(SECRET),
        autofix_label="autofix",
    )
    app = create_app(settings)
    db = Database.from_settings(settings)
    await db.create_all()
    app.state.db = db  # bypass lifespan; ASGITransport does not run it
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        c._db = db  # type: ignore[attr-defined]  # expose for assertions
        try:
            yield c
        finally:
            await db.dispose()


def _post(body: dict, *, event: str = "issues", sign: bool = True, secret: str = SECRET) -> dict:
    raw = json.dumps(body).encode("utf-8")
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if sign:
        headers["X-Hub-Signature-256"] = compute_signature(secret, raw)
    return {"content": raw, "headers": headers}


async def test_labeled_issue_creates_queued_job(client: httpx.AsyncClient) -> None:
    resp = await client.post("/webhooks/github", **_post(_payload()))
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"

    db: Database = client._db  # type: ignore[attr-defined]
    async with db.session() as session:
        job = (await session.execute(select(Job))).scalar_one()
    assert job.state == JobState.QUEUED
    assert job.gh_issue_number == 42


async def test_invalid_signature_is_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post("/webhooks/github", **_post(_payload(), secret="wrong"))
    assert resp.status_code == 401

    db: Database = client._db  # type: ignore[attr-defined]
    async with db.session() as session:
        jobs = (await session.execute(select(Job))).scalars().all()
    assert jobs == []  # nothing enqueued on a bad signature


async def test_non_issue_event_is_ignored(client: httpx.AsyncClient) -> None:
    resp = await client.post("/webhooks/github", **_post(_payload(), event="push"))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


async def test_other_label_is_ignored(client: httpx.AsyncClient) -> None:
    resp = await client.post("/webhooks/github", **_post(_payload(label="wontfix")))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


async def test_duplicate_delivery_is_idempotent(client: httpx.AsyncClient) -> None:
    first = await client.post("/webhooks/github", **_post(_payload(issue=8)))
    second = await client.post("/webhooks/github", **_post(_payload(issue=8)))
    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "exists"
    assert first.json()["job_id"] == second.json()["job_id"]


async def test_healthz(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
