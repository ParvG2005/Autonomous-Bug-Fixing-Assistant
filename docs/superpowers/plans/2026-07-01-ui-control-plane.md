# UI Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the React frontend the complete control surface — add repos, submit fixes, trigger scans, and publish draft PRs, all from the browser.

**Architecture:** Three additive layers over the existing system. (1) One Alembic migration relaxes `Repo` constraints so a repo can exist before a GitHub App install. (2) New FastAPI write endpoints create repos/jobs and delegate every GitHub network call (connect, scan, publish) to arq worker tasks, keeping the API process network-free. (3) New React surfaces: a Repos tab, a New Fix modal, and a Publish button. No change to the agent loop, sandbox, or solve pipeline.

**Tech Stack:** Python 3.12, FastAPI (async), SQLAlchemy 2.0 async, Alembic, arq + Redis, pytest; React + TypeScript + Vite + Tailwind, vitest.

## Global Constraints

- Python 3.12; async SQLAlchemy 2.0; ruff + mypy must stay clean (`ruff check`, `ruff format`, `mypy app`).
- API process is **network-free**: all GitHub I/O runs in arq worker tasks, never in a route handler. (SECURITY.md C4 — secret isolation.)
- Publishing a PR goes through the existing `assert_approved` chokepoint — no new bypass of the C1 human gate.
- Untrusted user input (manual issue body) is stored as an `issue_body` ARTIFACT, never inlined on the JOB row.
- API binds to localhost only; no auth (single-user, not deployed). Adding auth before deploy is a recorded follow-up — do not expose write endpoints publicly without it.
- Migrations only relax constraints / use VARCHAR enums (no new enum-type migration); `alembic check` must stay clean.
- `migrations/` uses async Alembic; generate revisions with `alembic revision -m ...` then hand-edit (autogenerate is unreliable for constraint relaxation on SQLite — write the ops explicitly).

---

## File Structure

**Create:**
- `app/db/repos.py` — repo CRUD service (parse URL, create/list/delete).
- `app/vcs/db_store.py` — `DbApprovalStore` adapting the DB `Approval` model to the `ApprovalStore` protocol.
- `app/api/repos.py` — `/repos` router (list/add/delete/connect/scan).
- `migrations/versions/<rev>_repo_nullable_install.py` — the migration.
- `frontend/src/components/RepoList.tsx` — Repos tab.
- `frontend/src/components/NewFixModal.tsx` — New Fix form.
- Tests: `tests/db/test_repos.py`, `tests/db/test_manual_ingest.py`, `tests/vcs/test_db_store.py`, `tests/workers/test_control_tasks.py`, `tests/api/test_repos_api.py`, `tests/api/test_manual_jobs_api.py`, `tests/api/test_publish_api.py`, `frontend/src/__tests__/RepoList.test.tsx`, `frontend/src/__tests__/NewFixModal.test.tsx`.

**Modify:**
- `app/models/entities.py` — `Repo.installation_id` / `Repo.gh_repo_id` nullable; add `ArtifactKind.BUNDLE`.
- `app/db/jobs.py` — add `ingest_manual_issue`.
- `app/workers/pipeline.py` — persist a `BUNDLE` artifact when a fix is produced.
- `app/workers/queue.py` — add generic `enqueue_task`.
- `app/workers/worker.py` — register `connect_repo`, `scan_repo`, `publish_pr` tasks.
- `app/workers/control_tasks.py` — **Create** (worker task bodies for connect/scan/publish).
- `app/api/jobs.py` — add `POST /jobs` and `POST /jobs/{id}/publish`.
- `app/api/main.py` — include the repos router.
- `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/App.tsx`, `frontend/src/components/JobDetail.tsx`.

---

## Milestone A — Data model

### Task 1: Relax `Repo` constraints + add `BUNDLE` artifact kind

**Files:**
- Modify: `app/models/entities.py:103-134`
- Create: `migrations/versions/<rev>_repo_nullable_install.py`
- Test: `tests/db/test_repos.py`

**Interfaces:**
- Produces: `Repo` may be created with `gh_repo_id=None`, `installation_id=None`. `ArtifactKind.BUNDLE = "bundle"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_repos.py
import pytest
from app.models.entities import ArtifactKind, Repo


def test_bundle_artifact_kind_exists():
    assert ArtifactKind.BUNDLE.value == "bundle"


@pytest.mark.asyncio
async def test_repo_persists_without_install(db_session):
    repo = Repo(full_name="octo/demo", default_branch="main")
    db_session.add(repo)
    await db_session.flush()
    assert repo.id is not None
    assert repo.installation_id is None
    assert repo.gh_repo_id is None
```

Use the existing async `db_session` fixture (see `tests/conftest.py`). If none exists at that path, mirror the fixture other `tests/db/*` files import.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_repos.py -v`
Expected: FAIL — `installation_id`/`gh_repo_id` are `NOT NULL` (IntegrityError) and `ArtifactKind.BUNDLE` missing (AttributeError).

- [ ] **Step 3: Edit the model**

In `app/models/entities.py`, change the `Repo` columns:

```python
    gh_repo_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    installation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
```

And add to `ArtifactKind` (VARCHAR enum — no migration needed for the value):

```python
    BUNDLE = "bundle"  # serialized FixBundle JSON for the publish path
```

- [ ] **Step 4: Generate and write the migration**

Run: `alembic revision -m "repo nullable install"`
Then replace the generated `upgrade`/`downgrade` with explicit batch ops (SQLite needs batch mode to alter columns):

```python
def upgrade() -> None:
    with op.batch_alter_table("repo") as batch:
        batch.alter_column("gh_repo_id", existing_type=sa.BigInteger(), nullable=True)
        batch.alter_column("installation_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("repo") as batch:
        batch.alter_column("installation_id", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("gh_repo_id", existing_type=sa.BigInteger(), nullable=False)
```

- [ ] **Step 5: Apply migration and verify clean**

Run: `alembic upgrade head && alembic check`
Expected: upgrade succeeds; `alembic check` prints "No new upgrade operations detected."

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/db/test_repos.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/models/entities.py migrations/versions tests/db/test_repos.py
git commit -m "feat(model): repo can exist before GitHub App install + BUNDLE artifact kind"
```

---

## Milestone B — Repos API

### Task 2: Repo CRUD service

**Files:**
- Create: `app/db/repos.py`
- Test: `tests/db/test_repos.py` (extend)

**Interfaces:**
- Produces:
  - `parse_repo_url(url: str) -> str` — returns `"owner/name"`; raises `ValueError` on a non-GitHub or malformed URL.
  - `async create_repo(session, full_name: str) -> Repo` — creates a fix-only repo (`installation_id=None`); raises `ValueError` if `full_name` already registered.
  - `async list_repos(session) -> list[Repo]` — newest first.
  - `async delete_repo(session, repo_id: uuid.UUID) -> None` — raises `ValueError` if the repo has a live job.

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_repos.py (append)
import pytest
from app.db.repos import create_repo, delete_repo, list_repos, parse_repo_url


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/octo/demo", "octo/demo"),
    ("https://github.com/octo/demo.git", "octo/demo"),
    ("git@github.com:octo/demo.git", "octo/demo"),
    ("octo/demo", "octo/demo"),
])
def test_parse_repo_url_ok(url, expected):
    assert parse_repo_url(url) == expected


@pytest.mark.parametrize("bad", ["", "https://gitlab.com/a/b", "not a url", "octo"])
def test_parse_repo_url_bad(bad):
    with pytest.raises(ValueError):
        parse_repo_url(bad)


@pytest.mark.asyncio
async def test_create_list_delete(db_session):
    repo = await create_repo(db_session, "octo/demo")
    assert repo.installation_id is None
    assert [r.full_name for r in await list_repos(db_session)] == ["octo/demo"]
    with pytest.raises(ValueError):
        await create_repo(db_session, "octo/demo")  # duplicate
    await delete_repo(db_session, repo.id)
    assert await list_repos(db_session) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_repos.py -v`
Expected: FAIL — `app.db.repos` does not exist (ImportError).

- [ ] **Step 3: Implement the service**

```python
# app/db/repos.py
"""Repo registration service for the UI control plane.

A repo can be added by URL with no GitHub App install (``installation_id`` NULL,
"fix-only"); ``app.workers.control_tasks.connect_repo`` upgrades it later. The
fix pipeline clones from ``full_name`` so no install is required to fix.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Job, JobState, Repo

_LIVE = (JobState.QUEUED, JobState.RUNNING, JobState.AWAITING_APPROVAL, JobState.APPROVED)
_URL_RE = re.compile(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_SHORT_RE = re.compile(r"^([\w.-]+)/([\w.-]+?)(?:\.git)?$")


def parse_repo_url(url: str) -> str:
    """Return ``owner/name`` from a GitHub URL or shorthand; raise on anything else."""
    url = (url or "").strip()
    if not url:
        raise ValueError("empty repo url")
    m = _URL_RE.search(url) or (_SHORT_RE.match(url) if "github.com" not in url else None)
    if m is None:
        raise ValueError(f"not a GitHub repo url: {url!r}")
    return f"{m.group(1)}/{m.group(2)}"


async def _by_full_name(session: AsyncSession, full_name: str) -> Repo | None:
    return (
        await session.execute(select(Repo).where(Repo.full_name == full_name))
    ).scalar_one_or_none()


async def create_repo(session: AsyncSession, full_name: str) -> Repo:
    if await _by_full_name(session, full_name) is not None:
        raise ValueError(f"repo {full_name} already registered")
    repo = Repo(full_name=full_name, default_branch="main")
    session.add(repo)
    await session.flush()
    return repo


async def list_repos(session: AsyncSession) -> list[Repo]:
    rows = await session.execute(select(Repo).order_by(Repo.created_at.desc()))
    return list(rows.scalars().all())


async def delete_repo(session: AsyncSession, repo_id: uuid.UUID) -> None:
    live = (
        await session.execute(
            select(Job.id).where(Job.repo_id == repo_id, Job.state.in_(_LIVE)).limit(1)
        )
    ).first()
    if live is not None:
        raise ValueError("repo has a live job; cannot delete")
    repo = (await session.execute(select(Repo).where(Repo.id == repo_id))).scalar_one_or_none()
    if repo is not None:
        await session.delete(repo)
        await session.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/db/test_repos.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/db/repos.py tests/db/test_repos.py
git commit -m "feat(db): repo CRUD service + GitHub URL parsing"
```

---

### Task 3: Generic worker enqueue + task registration scaffold

**Files:**
- Modify: `app/workers/queue.py:42-60`, `app/workers/worker.py:70-83`
- Create: `app/workers/control_tasks.py`
- Test: `tests/workers/test_control_tasks.py`

**Interfaces:**
- Produces:
  - `JobQueue.enqueue_task(task: str, *args, dedup_key: str | None = None) -> bool`.
  - `app/workers/control_tasks.py` with async stubs `connect_repo(ctx, repo_id)`, `scan_repo(ctx, repo_id)`, `publish_pr(ctx, job_id)` (filled in Tasks 4, 5, 8). Each takes `ctx: dict[str, Any]` and a string id.
- Consumes: `ctx["db"]`, `ctx["settings"]` (set by `worker.startup`).

- [ ] **Step 1: Write the failing test**

```python
# tests/workers/test_control_tasks.py
import pytest
from app.workers import control_tasks
from app.workers.queue import JobQueue


class _FakePool:
    def __init__(self): self.calls = []
    async def enqueue_job(self, task, *args, _job_id=None):
        self.calls.append((task, args, _job_id))
        return object()


@pytest.mark.asyncio
async def test_enqueue_task_passes_name_and_args():
    pool = _FakePool()
    q = JobQueue(pool)
    ok = await q.enqueue_task("scan_repo", "rid-1", dedup_key="scan:rid-1")
    assert ok is True
    assert pool.calls == [("scan_repo", ("rid-1",), "scan:rid-1")]


def test_control_tasks_are_async_callables():
    for name in ("connect_repo", "scan_repo", "publish_pr"):
        assert callable(getattr(control_tasks, name))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/workers/test_control_tasks.py -v`
Expected: FAIL — `enqueue_task` missing; `app.workers.control_tasks` missing.

- [ ] **Step 3: Add `enqueue_task` to `JobQueue`**

In `app/workers/queue.py`, add this method to `JobQueue` (after `enqueue`):

```python
    async def enqueue_task(
        self, task: str, *args: object, dedup_key: str | None = None
    ) -> bool:
        """Enqueue an arbitrary worker task. Dedup by ``dedup_key`` when given."""
        kwargs = {"_job_id": dedup_key} if dedup_key else {}
        job = await self._pool.enqueue_job(task, *args, **kwargs)  # type: ignore[attr-defined]
        enqueued = job is not None
        log.info("enqueue_task", task=task, enqueued=enqueued)
        return enqueued
```

- [ ] **Step 4: Create the control-task stubs**

```python
# app/workers/control_tasks.py
"""Worker tasks for the UI control plane: GitHub I/O kept off the API process.

``connect_repo`` / ``scan_repo`` / ``publish_pr`` are enqueued by the API and run
here where network + token minting are allowed (SECURITY.md C4).
"""

from __future__ import annotations

from typing import Any

from app.telemetry.logging import get_logger

log = get_logger("workers.control")


async def connect_repo(ctx: dict[str, Any], repo_id: str) -> str:
    raise NotImplementedError  # Task 4


async def scan_repo(ctx: dict[str, Any], repo_id: str) -> str:
    raise NotImplementedError  # Task 5


async def publish_pr(ctx: dict[str, Any], job_id: str) -> str:
    raise NotImplementedError  # Task 8
```

- [ ] **Step 5: Register the tasks**

In `app/workers/worker.py`, import the stubs and extend `functions`:

```python
from app.workers.control_tasks import connect_repo, publish_pr, scan_repo
```

```python
    functions: ClassVar[list[Callable[..., Any]]] = [run_job, connect_repo, scan_repo, publish_pr]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/workers/test_control_tasks.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/workers/queue.py app/workers/worker.py app/workers/control_tasks.py tests/workers/test_control_tasks.py
git commit -m "feat(workers): generic task enqueue + control-task registration"
```

---

### Task 4: `connect_repo` task — resolve install via GitHub App

**Files:**
- Modify: `app/workers/control_tasks.py`
- Test: `tests/workers/test_control_tasks.py` (extend)

**Interfaces:**
- Consumes: `app.vcs.auth` (App auth), `Repo` row by id, `ctx["db"]`, `ctx["settings"]`.
- Produces: sets `Repo.gh_repo_id` + `Repo.installation_id` on success; sets neither and logs on failure. Returns `"connected"` / `"unavailable"`.

Resolution uses the GitHub App to look up the installation for the repo. Use the existing helper if one exists in `app/vcs/auth.py` (search for an installation-lookup function); otherwise call the REST endpoint `GET /repos/{owner}/{name}/installation` with a JWT minted by `app.vcs.auth`. The implementer must read `app/vcs/auth.py` first and reuse its JWT/token primitives rather than re-implementing them.

- [ ] **Step 1: Write the failing test** (inject a fake resolver so no network)

```python
# tests/workers/test_control_tasks.py (append)
import pytest
from app.db.repos import create_repo
from app.models.entities import Repo
from sqlalchemy import select


@pytest.mark.asyncio
async def test_connect_repo_sets_install(db, monkeypatch):
    # `db` = a Database whose .session() yields a session bound to the test engine.
    async with db.session() as s:
        repo = await create_repo(s, "octo/demo")
        await s.commit()
        rid = str(repo.id)

    async def fake_resolve(settings, full_name):
        return (12345, 67890)  # (gh_repo_id, installation_id)

    monkeypatch.setattr("app.workers.control_tasks._resolve_installation", fake_resolve)
    ctx = {"db": db, "settings": object()}
    result = await __import__("app.workers.control_tasks", fromlist=["connect_repo"]).connect_repo(ctx, rid)
    assert result == "connected"
    async with db.session() as s:
        repo = (await s.execute(select(Repo).where(Repo.id == repo.id))).scalar_one()
        assert repo.installation_id == 67890
        assert repo.gh_repo_id == 12345
```

If no `db` fixture exists, add one in `tests/conftest.py` that builds `Database` against the test SQLite URL (mirror how `tests/workers/` builds it elsewhere).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/workers/test_control_tasks.py::test_connect_repo_sets_install -v`
Expected: FAIL — `connect_repo` raises `NotImplementedError`; `_resolve_installation` missing.

- [ ] **Step 3: Implement**

```python
# app/workers/control_tasks.py — replace the connect_repo stub and add the helper
import uuid

from sqlalchemy import select

from app.models.entities import Repo


async def _resolve_installation(settings: object, full_name: str) -> tuple[int, int]:
    """Return ``(gh_repo_id, installation_id)`` for ``full_name`` via the GitHub App.

    Reads App credentials from ``settings`` and calls
    ``GET /repos/{full_name}/installation`` + ``GET /repos/{full_name}`` with an
    App JWT. Reuse the JWT/token primitives in ``app.vcs.auth`` — do not
    re-implement signing here. Raises on a repo the App is not installed on.
    """
    from app.vcs.auth import resolve_repo_installation  # implement/locate in auth.py

    return await resolve_repo_installation(settings, full_name)


async def connect_repo(ctx: dict[str, Any], repo_id: str) -> str:
    db = ctx["db"]
    settings = ctx["settings"]
    async with db.session() as session:
        repo = (
            await session.execute(select(Repo).where(Repo.id == uuid.UUID(repo_id)))
        ).scalar_one_or_none()
        if repo is None:
            return "unavailable"
        try:
            gh_repo_id, installation_id = await _resolve_installation(settings, repo.full_name)
        except Exception as exc:  # App not installed / network — stay fix-only
            log.warning("connect_failed", repo=repo.full_name, error=str(exc))
            return "unavailable"
        repo.gh_repo_id = gh_repo_id
        repo.installation_id = installation_id
        await session.commit()
    log.info("repo_connected", repo_id=repo_id)
    return "connected"
```

If `resolve_repo_installation` does not already exist in `app/vcs/auth.py`, add it there next to the existing token minting, using the same `httpx`/JWT helpers that file already imports. Keep all signing in `auth.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/workers/test_control_tasks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/control_tasks.py app/vcs/auth.py tests/workers/test_control_tasks.py
git commit -m "feat(workers): connect_repo resolves GitHub App install for a repo"
```

---

### Task 5: `scan_repo` task — clone + run discovery

**Files:**
- Modify: `app/workers/control_tasks.py`
- Test: `tests/workers/test_control_tasks.py` (extend)

**Interfaces:**
- Consumes: `app.index.clone.clone_repo`, `app.discovery.service.run_scan`, `app.sandbox.get_sandbox`, `ScanTrigger.MANUAL`.
- Produces: clones the repo to `settings.workspace_root / f"scan-{rid}"`, runs `run_scan(..., promote=False)` so findings appear in the Findings tab without spending tokens. Returns `"scanned"`.

- [ ] **Step 1: Write the failing test** (patch clone + run_scan so no network/Docker)

```python
# tests/workers/test_control_tasks.py (append)
@pytest.mark.asyncio
async def test_scan_repo_clones_and_scans(db, monkeypatch, tmp_path):
    async with db.session() as s:
        repo = await create_repo(s, "octo/demo")
        await s.commit()
        rid = str(repo.id)

    calls = {}
    def fake_clone(url, dest, **kw): calls["clone"] = (url, dest); return dest
    async def fake_run_scan(database, full_name, workspace, **kw):
        calls["scan"] = (full_name, kw.get("promote"))
        from app.discovery.service import ScanSummary
        return ScanSummary(scan_id="s1", sources_run=[], candidates=0, parked=0, duplicates=0, errors={})
    monkeypatch.setattr("app.workers.control_tasks.clone_repo", fake_clone)
    monkeypatch.setattr("app.workers.control_tasks.run_scan", fake_run_scan)
    monkeypatch.setattr("app.workers.control_tasks.get_sandbox", lambda: object())

    ctx = {"db": db, "settings": __import__("app.core.settings", fromlist=["get_settings"]).get_settings()}
    result = await __import__("app.workers.control_tasks", fromlist=["scan_repo"]).scan_repo(ctx, rid)
    assert result == "scanned"
    assert calls["clone"][0] == "https://github.com/octo/demo.git"
    assert calls["scan"] == ("octo/demo", False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/workers/test_control_tasks.py::test_scan_repo_clones_and_scans -v`
Expected: FAIL — `scan_repo` raises `NotImplementedError`.

- [ ] **Step 3: Implement**

```python
# app/workers/control_tasks.py — add imports + replace scan_repo stub
from app.discovery.service import run_scan
from app.discovery.sources import DEFAULT_DETECTORS
from app.index.clone import clone_repo
from app.models.entities import ScanTrigger
from app.sandbox import get_sandbox


async def scan_repo(ctx: dict[str, Any], repo_id: str) -> str:
    db = ctx["db"]
    settings = ctx["settings"]
    async with db.session() as session:
        repo = (
            await session.execute(select(Repo).where(Repo.id == uuid.UUID(repo_id)))
        ).scalar_one_or_none()
        if repo is None:
            return "unavailable"
        full_name = repo.full_name
    workspace = (settings.workspace_root / f"scan-{repo_id}").resolve()
    await asyncio.to_thread(
        clone_repo, f"https://github.com/{full_name}.git", workspace, depth=1
    )
    await run_scan(
        db,
        full_name,
        workspace,
        detectors=DEFAULT_DETECTORS,
        sandbox=get_sandbox(),
        trigger=ScanTrigger.MANUAL,
        promote=False,  # record candidates only; promotion stays a human gate in Findings
    )
    log.info("repo_scanned", repo_id=repo_id)
    return "scanned"
```

Add `import asyncio` at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/workers/test_control_tasks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/control_tasks.py tests/workers/test_control_tasks.py
git commit -m "feat(workers): scan_repo clones a repo and records findings"
```

---

### Task 6: `/repos` router (list/add/delete/connect/scan)

**Files:**
- Create: `app/api/repos.py`
- Modify: `app/api/main.py:60-63`
- Test: `tests/api/test_repos_api.py`

**Interfaces:**
- Consumes: `app.db.repos` service, `get_session`, `get_queue`, `JobQueue.enqueue_task`.
- Produces endpoints: `GET /repos`, `POST /repos {clone_url}`, `DELETE /repos/{id}`, `POST /repos/{id}/connect`, `POST /repos/{id}/scan`. `RepoView` fields: `id, full_name, publish_capable (installation_id is not None), created_at`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_repos_api.py
import pytest


@pytest.mark.asyncio
async def test_add_list_delete_repo(api_client):
    # api_client = httpx.AsyncClient over the app with a queue stub on app.state.
    r = await api_client.post("/repos", json={"clone_url": "https://github.com/octo/demo"})
    assert r.status_code == 201
    body = r.json()
    assert body["full_name"] == "octo/demo"
    assert body["publish_capable"] is False

    r = await api_client.get("/repos")
    assert [x["full_name"] for x in r.json()] == ["octo/demo"]

    r = await api_client.delete(f"/repos/{body['id']}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_add_repo_bad_url(api_client):
    r = await api_client.post("/repos", json={"clone_url": "not-a-url"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_scan_enqueues(api_client, queue_stub):
    r = await api_client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]
    r = await api_client.post(f"/repos/{rid}/scan")
    assert r.status_code == 202
    assert ("scan_repo", (rid,)) in [(t, a) for (t, a, _k) in queue_stub.tasks]
```

Reuse / extend the API test harness used by `tests/api/` (look for the existing app + client fixture; add a `queue_stub` that records `enqueue_task` calls and is attached to `app.state.queue`).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_repos_api.py -v`
Expected: FAIL — `/repos` routes return 404 (router not registered).

- [ ] **Step 3: Implement the router**

```python
# app/api/repos.py
"""Repo management endpoints for the UI control plane.

Add a repo by URL (fix-only), list, delete, and — via worker tasks that own all
GitHub I/O — connect a GitHub App install or trigger a discovery scan.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_queue, get_session
from app.db.repos import create_repo, delete_repo, list_repos, parse_repo_url
from app.workers.queue import JobQueue

router = APIRouter(prefix="/repos", tags=["repos"])


class AddRepoBody(BaseModel):
    clone_url: str


class RepoView(BaseModel):
    id: str
    full_name: str
    publish_capable: bool
    created_at: datetime


def _view(repo: object) -> RepoView:
    return RepoView(
        id=str(repo.id),
        full_name=repo.full_name,
        publish_capable=repo.installation_id is not None,
        created_at=repo.created_at,
    )


def _parse_id(repo_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(repo_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed repo id") from exc


@router.get("", response_model=list[RepoView])
async def get_repos(session: AsyncSession = Depends(get_session)) -> list[RepoView]:
    return [_view(r) for r in await list_repos(session)]


@router.post("", response_model=RepoView, status_code=status.HTTP_201_CREATED)
async def add_repo(
    body: AddRepoBody, session: AsyncSession = Depends(get_session)
) -> RepoView:
    try:
        full_name = parse_repo_url(body.clone_url)
        repo = await create_repo(session, full_name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return _view(repo)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_repo(
    repo_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    try:
        await delete_repo(session, _parse_id(repo_id))
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()


async def _enqueue(queue: object | None, task: str, repo_id: str) -> None:
    if not isinstance(queue, JobQueue):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "worker queue not configured")
    await queue.enqueue_task(task, repo_id, dedup_key=f"{task}:{repo_id}")


@router.post("/{repo_id}/connect", status_code=status.HTTP_202_ACCEPTED)
async def connect(repo_id: str, queue: object | None = Depends(get_queue)) -> dict[str, str]:
    await _enqueue(queue, "connect_repo", repo_id)
    return {"status": "connecting", "repo_id": repo_id}


@router.post("/{repo_id}/scan", status_code=status.HTTP_202_ACCEPTED)
async def scan(repo_id: str, queue: object | None = Depends(get_queue)) -> dict[str, str]:
    await _enqueue(queue, "scan_repo", repo_id)
    return {"status": "scanning", "repo_id": repo_id}
```

- [ ] **Step 4: Register the router**

In `app/api/main.py`, after the other `include_router` lines:

```python
    from app.api.repos import router as repos_router
    app.include_router(repos_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/api/test_repos_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/api/repos.py app/api/main.py tests/api/test_repos_api.py
git commit -m "feat(api): /repos endpoints (add/list/delete/connect/scan)"
```

---

## Milestone C — New Fix

### Task 7: `ingest_manual_issue` service

**Files:**
- Modify: `app/db/jobs.py` (append after `ingest_labeled_issue`)
- Test: `tests/db/test_manual_ingest.py`

**Interfaces:**
- Consumes: `Repo` by id, `Artifact`, `Job`, `JobTrigger.MANUAL`, `JobState.QUEUED`, `_DEFAULT_BUDGET`.
- Produces: `async ingest_manual_issue(session, *, repo_id: uuid.UUID, body: str, title: str | None) -> Job`. Stores `body` as an `ISSUE_BODY` artifact, links `job.issue_body_ref`, `gh_issue_number=None`, `trigger=MANUAL`. Raises `ValueError` if the repo does not exist.

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_manual_ingest.py
import pytest
from app.db.jobs import ingest_manual_issue
from app.db.repos import create_repo
from app.models.entities import Artifact, ArtifactKind, JobState, JobTrigger
from sqlalchemy import select


@pytest.mark.asyncio
async def test_manual_ingest_stores_body_and_queues(db_session):
    repo = await create_repo(db_session, "octo/demo")
    job = await ingest_manual_issue(
        db_session, repo_id=repo.id, body="boom\nTraceback ...", title="crash on save"
    )
    assert job.trigger == JobTrigger.MANUAL
    assert job.gh_issue_number is None
    assert job.state == JobState.QUEUED
    assert job.issue_title == "crash on save"
    art = (
        await db_session.execute(select(Artifact).where(Artifact.id == job.issue_body_ref))
    ).scalar_one()
    assert art.kind == ArtifactKind.ISSUE_BODY
    assert art.content == "boom\nTraceback ..."


@pytest.mark.asyncio
async def test_manual_ingest_unknown_repo(db_session):
    import uuid
    with pytest.raises(ValueError):
        await ingest_manual_issue(db_session, repo_id=uuid.uuid4(), body="x", title=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_manual_ingest.py -v`
Expected: FAIL — `ingest_manual_issue` not defined.

- [ ] **Step 3: Implement** (append to `app/db/jobs.py`)

```python
async def ingest_manual_issue(
    session: AsyncSession,
    *,
    repo_id: object,
    body: str,
    title: str | None,
) -> Job:
    """Create a queued MANUAL job from UI-submitted issue text / stack trace.

    The body is untrusted, so it is stored as an ISSUE_BODY artifact and only
    referenced from the job (never inlined). There is no GitHub issue number.
    """
    repo = (await session.execute(select(Repo).where(Repo.id == repo_id))).scalar_one_or_none()
    if repo is None:
        raise ValueError(f"repo {repo_id} not found")

    body = body or ""
    body_bytes = body.encode("utf-8")
    artifact = Artifact(
        job_id=None,
        kind=ArtifactKind.ISSUE_BODY,
        storage=ArtifactStorage.INLINE_SMALL,
        content=body,
        size_bytes=len(body_bytes),
        sha256=hashlib.sha256(body_bytes).hexdigest(),
    )
    job = Job(
        repo_id=repo.id,
        gh_issue_number=None,
        trigger=JobTrigger.MANUAL,
        issue_title=title,
        state=JobState.QUEUED,
        budget=dict(_DEFAULT_BUDGET),
        cost={},
    )
    session.add(job)
    await session.flush()
    artifact.job_id = job.id
    session.add(artifact)
    await session.flush()
    job.issue_body_ref = artifact.id
    await session.flush()
    return job
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/db/test_manual_ingest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/db/jobs.py tests/db/test_manual_ingest.py
git commit -m "feat(db): ingest_manual_issue — UI-submitted fix jobs"
```

---

### Task 8: `POST /jobs` endpoint

**Files:**
- Modify: `app/api/jobs.py` (add route + body model; reuse `JobView`/`_load_job_view`)
- Test: `tests/api/test_manual_jobs_api.py`

**Interfaces:**
- Consumes: `ingest_manual_issue`, `get_queue`, `JobQueue.enqueue`.
- Produces: `POST /jobs {repo_id, body, title?}` → 201 with a `JobView`; enqueues `run_job`. 400 on unknown repo / empty body.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_manual_jobs_api.py
import pytest


@pytest.mark.asyncio
async def test_create_manual_job(api_client, queue_stub):
    r = await api_client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]
    r = await api_client.post("/jobs", json={"repo_id": rid, "body": "Traceback...", "title": "boom"})
    assert r.status_code == 201
    job = r.json()
    assert job["state"] == "queued"
    assert job["id"] in [str(a[0]) for a in queue_stub.jobs]  # enqueue(job_id) called


@pytest.mark.asyncio
async def test_create_job_unknown_repo(api_client):
    import uuid
    r = await api_client.post("/jobs", json={"repo_id": str(uuid.uuid4()), "body": "x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_job_empty_body(api_client):
    r = await api_client.post("/repos", json={"clone_url": "octo/demo"})
    rid = r.json()["id"]
    r = await api_client.post("/jobs", json={"repo_id": rid, "body": "   "})
    assert r.status_code == 400
```

Extend `queue_stub` to record `enqueue(job_id)` calls in `.jobs`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_manual_jobs_api.py -v`
Expected: FAIL — `POST /jobs` returns 405/404.

- [ ] **Step 3: Implement** (add to `app/api/jobs.py`)

```python
from app.db.jobs import ingest_manual_issue
from app.api.deps import get_queue


class CreateJobBody(BaseModel):
    repo_id: str
    body: str
    title: str | None = None


@router.post("/jobs", response_model=JobView, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: CreateJobBody,
    session: AsyncSession = Depends(get_session),
    queue: object | None = Depends(get_queue),
) -> JobView:
    if not payload.body.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "issue body is empty")
    try:
        job = await ingest_manual_issue(
            session,
            repo_id=_parse_job_id(payload.repo_id),
            body=payload.body,
            title=payload.title,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    view = await _load_job_view(session, job.id)
    await session.commit()
    from app.workers.queue import JobQueue

    if isinstance(queue, JobQueue):
        await queue.enqueue(job.id)
    return view
```

(`_parse_job_id` already validates a UUID and raises 400 on a malformed id — reused for `repo_id`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_manual_jobs_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/jobs.py tests/api/test_manual_jobs_api.py
git commit -m "feat(api): POST /jobs — submit a fix from the UI"
```

---

## Milestone D — Publish

### Task 9: Persist a `BUNDLE` artifact in the pipeline

**Files:**
- Modify: `app/workers/pipeline.py:190-200`
- Test: `tests/workers/test_pipeline_bundle.py`

**Interfaces:**
- Consumes: `build_fix_bundle` (`app.vcs.bundle`), `RepoRef` (`app.vcs.models`), `SolveResult`.
- Produces: a `BUNDLE` artifact whose `content` is JSON matching the CLI's `_bundle_from_json` shape (`job_id, repo{owner,name,installation_id}, base_branch, head_branch, title, commit_message, body, changes[{path,content}], reasoning_comment`). Only written when `agent.edits` is non-empty.

- [ ] **Step 1: Write the failing test**

Read `app/workers/pipeline.py` first to match the offline test harness (fake client + LocalSandbox + fixture clone) the other pipeline tests use. The new test runs a job to completion and asserts a `BUNDLE` artifact exists and round-trips:

```python
# tests/workers/test_pipeline_bundle.py
import json
import pytest
from app.models.entities import Artifact, ArtifactKind
from sqlalchemy import select
# ... reuse the pipeline test fixtures (fake solve fn returning a SolveResult with edits)


@pytest.mark.asyncio
async def test_pipeline_writes_bundle_artifact(pipeline_env):
    job_id = await run_one_job_with_edits(pipeline_env)  # helper from existing pipeline tests
    async with pipeline_env.db.session() as s:
        art = (
            await s.execute(
                select(Artifact).where(
                    Artifact.job_id == job_id, Artifact.kind == ArtifactKind.BUNDLE
                )
            )
        ).scalar_one()
    raw = json.loads(art.content)
    assert raw["job_id"] == str(job_id)
    assert raw["changes"]  # full-file changes present
    assert raw["repo"]["owner"] and raw["repo"]["name"]
```

If the existing pipeline test module already has a "writes artifacts" test, add this assertion there instead of a new file and skip the new file.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/workers/test_pipeline_bundle.py -v`
Expected: FAIL — no BUNDLE artifact (`NoResultFound`).

- [ ] **Step 3: Implement** — after the DIFF/REASONING artifacts are built (around `pipeline.py:192-195`):

```python
        from app.vcs.bundle import build_fix_bundle
        from app.vcs.models import RepoRef

        bundle_artifact = None
        if agent.edits:
            owner, _, name = repo.full_name.partition("/")
            bundle = build_fix_bundle(
                job_id=str(job.id),
                repo=RepoRef(owner=owner, name=name, installation_id=repo.installation_id or 0),
                base_branch=repo.default_branch,
                result=result,
            )
            bundle_json = json.dumps(
                {
                    "job_id": bundle.job_id,
                    "repo": {"owner": owner, "name": name,
                             "installation_id": repo.installation_id or 0},
                    "base_branch": bundle.base_branch,
                    "head_branch": bundle.head_branch,
                    "title": bundle.title,
                    "commit_message": bundle.commit_message,
                    "body": bundle.body,
                    "changes": [{"path": c.path, "content": c.content} for c in bundle.changes],
                    "reasoning_comment": bundle.reasoning_comment,
                },
                indent=2,
            )
            bundle_artifact = _artifact(job.id, ArtifactKind.BUNDLE, bundle_json)
```

Then add `bundle_artifact` to the list of artifacts persisted in the same `session.add_all([...])` / add block (follow the existing pattern at lines 192-200; only append it when not `None`). `installation_id or 0` is a placeholder — the publish path re-reads the live `Repo.installation_id` (Task 11) and refuses when it is null, so the stored `0` is never used to mint a token.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/workers/test_pipeline_bundle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/pipeline.py tests/workers/test_pipeline_bundle.py
git commit -m "feat(pipeline): persist FixBundle as a BUNDLE artifact for UI publish"
```

---

### Task 10: `DbApprovalStore` adapter

**Files:**
- Create: `app/vcs/db_store.py`
- Test: `tests/vcs/test_db_store.py`

**Interfaces:**
- Consumes: DB `Approval` model + `latest_decision` (`app.db.approvals`), the vcs `Approval`/`Decision` types (`app.vcs.approval`), `ApprovalDecision` (`app.models.entities`).
- Produces: `DbApprovalStore(decisions: list)` — a synchronous `ApprovalStore` (`record`, `latest`) built from already-loaded DB rows, so `assert_approved` (sync) can run inside the worker without awaiting. Factory `async load_db_approval_store(session, job_id) -> DbApprovalStore` fetches the latest decision and wraps it.

The publish call (`open_draft_pr_for_fix`) is synchronous and calls `store.latest(job_id)`. So we load the DB decision *before* calling it and hand over a pre-populated, in-memory store.

- [ ] **Step 1: Write the failing test**

```python
# tests/vcs/test_db_store.py
import pytest
from app.db.approvals import record_decision
from app.db.repos import create_repo
from app.db.jobs import ingest_manual_issue
from app.models.entities import ApprovalDecision
from app.vcs.approval import Decision, assert_approved, ApprovalError
from app.vcs.db_store import load_db_approval_store


@pytest.mark.asyncio
async def test_db_store_reflects_approval(db_session):
    repo = await create_repo(db_session, "octo/demo")
    job = await ingest_manual_issue(db_session, repo_id=repo.id, body="x", title="t")
    await record_decision(db_session, job.id, ApprovalDecision.APPROVED, actor="me")
    store = await load_db_approval_store(db_session, str(job.id))
    latest = store.latest(str(job.id))
    assert latest is not None and latest.decision is Decision.APPROVED
    assert_approved(store, str(job.id))  # does not raise


@pytest.mark.asyncio
async def test_db_store_unapproved_raises(db_session):
    repo = await create_repo(db_session, "octo/demo")
    job = await ingest_manual_issue(db_session, repo_id=repo.id, body="x", title="t")
    store = await load_db_approval_store(db_session, str(job.id))
    with pytest.raises(ApprovalError):
        assert_approved(store, str(job.id))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/vcs/test_db_store.py -v`
Expected: FAIL — `app.vcs.db_store` missing.

- [ ] **Step 3: Implement**

```python
# app/vcs/db_store.py
"""Adapt the DB approval record to the publish path's ``ApprovalStore`` protocol.

The DB is the source of truth for UI approvals (``app.db.approvals``). The publish
call (`open_draft_pr_for_fix`) is synchronous, so we pre-load the latest decision
and hand it a populated in-memory store rather than awaiting inside the gate.
"""

from __future__ import annotations

from app.db.approvals import latest_decision
from app.models.entities import ApprovalDecision
from app.vcs.approval import Approval, Decision, InMemoryApprovalStore

_MAP = {
    ApprovalDecision.APPROVED: Decision.APPROVED,
    ApprovalDecision.REJECTED: Decision.REJECTED,
}


class DbApprovalStore(InMemoryApprovalStore):
    """An in-memory store pre-seeded from the DB. Read-only in practice."""


async def load_db_approval_store(session: object, job_id: str) -> DbApprovalStore:
    import uuid

    store = DbApprovalStore()
    row = await latest_decision(session, uuid.UUID(job_id))
    if row is not None:
        store.record(
            Approval(
                job_id=job_id,
                decision=_MAP[row.decision],
                actor=row.actor,
                decided_at=row.decided_at.isoformat(),
                note=row.note or "",
            )
        )
    return store
```

If `InMemoryApprovalStore.record`/`latest` key on `job_id` differently than the UUID string, match the key format `assert_approved` expects (read `app/vcs/approval.py:66-90`). Adjust the `Approval(job_id=...)` value to whatever `assert_approved(store, str(job.id))` looks up.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/vcs/test_db_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/vcs/db_store.py tests/vcs/test_db_store.py
git commit -m "feat(vcs): DB-backed ApprovalStore for the publish path"
```

---

### Task 11: `publish_pr` worker task

**Files:**
- Modify: `app/workers/control_tasks.py`
- Test: `tests/workers/test_control_tasks.py` (extend)

**Interfaces:**
- Consumes: the `BUNDLE` artifact (Task 9), `load_db_approval_store` (Task 10), `app.vcs.publish.open_draft_pr_for_fix`, `app.vcs.auth.settings_token_minter`, the live `Repo.installation_id`.
- Produces: rebuilds a `FixBundle` from the artifact with the *live* `installation_id`, asserts approval, opens the draft PR, and records the PR URL as a `REASONING`-adjacent note on the job (set `job.failure_reason=None` and store the URL in a new `LOG`/`REASONING` artifact, or — simplest — write the URL into the job's `cost` JSON under `"pr_url"`). Returns the PR URL or an error string. Refuses if `installation_id` is null or not approved.

- [ ] **Step 1: Write the failing test** (fake minter + fake client so no network)

```python
# tests/workers/test_control_tasks.py (append)
@pytest.mark.asyncio
async def test_publish_pr_opens_draft(db, monkeypatch):
    # Build a repo (with install), a job, an approved decision, and a BUNDLE artifact.
    from app.db.repos import create_repo
    from app.db.jobs import ingest_manual_issue
    from app.db.approvals import record_decision
    from app.models.entities import Artifact, ArtifactKind, ApprovalDecision
    import json, uuid

    async with db.session() as s:
        repo = await create_repo(s, "octo/demo")
        repo.installation_id = 999
        job = await ingest_manual_issue(s, repo_id=repo.id, body="x", title="t")
        await record_decision(s, job.id, ApprovalDecision.APPROVED, actor="me")
        s.add(Artifact(
            job_id=job.id, kind=ArtifactKind.BUNDLE, storage=__import__(
                "app.models.entities", fromlist=["ArtifactStorage"]).ArtifactStorage.INLINE_SMALL,
            content=json.dumps({
                "job_id": str(job.id),
                "repo": {"owner": "octo", "name": "demo", "installation_id": 0},
                "base_branch": "main", "head_branch": f"bugfix/{job.id}",
                "title": "Fix: t", "commit_message": "Fix: t", "body": "b",
                "changes": [{"path": "a.py", "content": "print(1)\n"}],
                "reasoning_comment": "why",
            }),
            size_bytes=1, sha256="x",
        ))
        await s.commit()
        jid = str(job.id)

    class FakePR: number = 7; url = "https://github.com/octo/demo/pull/7"
    def fake_publish(bundle, *, store, token_minter, **kw):
        assert bundle.repo.installation_id == 999  # live id, not the stored 0
        return FakePR()
    monkeypatch.setattr("app.workers.control_tasks.open_draft_pr_for_fix", fake_publish)
    monkeypatch.setattr("app.workers.control_tasks.settings_token_minter", lambda s, *, now: (lambda iid: "tok"))

    ctx = {"db": db, "settings": __import__("app.core.settings", fromlist=["get_settings"]).get_settings()}
    result = await __import__("app.workers.control_tasks", fromlist=["publish_pr"]).publish_pr(ctx, jid)
    assert result == "https://github.com/octo/demo/pull/7"


@pytest.mark.asyncio
async def test_publish_pr_refuses_without_install(db):
    from app.db.repos import create_repo
    from app.db.jobs import ingest_manual_issue
    import uuid
    async with db.session() as s:
        repo = await create_repo(s, "octo/demo")  # installation_id None
        job = await ingest_manual_issue(s, repo_id=repo.id, body="x", title="t")
        await s.commit()
        jid = str(job.id)
    ctx = {"db": db, "settings": object()}
    result = await __import__("app.workers.control_tasks", fromlist=["publish_pr"]).publish_pr(ctx, jid)
    assert result == "not_publish_capable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/workers/test_control_tasks.py -k publish -v`
Expected: FAIL — `publish_pr` raises `NotImplementedError`.

- [ ] **Step 3: Implement**

```python
# app/workers/control_tasks.py — add imports + replace publish_pr stub
import json
from datetime import UTC, datetime

from app.models.entities import Artifact, ArtifactKind
from app.vcs.auth import settings_token_minter
from app.vcs.db_store import load_db_approval_store
from app.vcs.models import FileChange, FixBundle, RepoRef
from app.vcs.publish import open_draft_pr_for_fix
from sqlalchemy import select


def _bundle_from_artifact(raw: dict, installation_id: int) -> FixBundle:
    repo = RepoRef(owner=raw["repo"]["owner"], name=raw["repo"]["name"],
                   installation_id=installation_id)
    return FixBundle(
        job_id=raw["job_id"], repo=repo,
        base_branch=raw["base_branch"], head_branch=raw["head_branch"],
        title=raw["title"], commit_message=raw["commit_message"], body=raw["body"],
        changes=[FileChange(**c) for c in raw["changes"]],
        reasoning_comment=raw.get("reasoning_comment", ""),
    )


async def publish_pr(ctx: dict[str, Any], job_id: str) -> str:
    db = ctx["db"]
    settings = ctx["settings"]
    async with db.session() as session:
        from app.models.entities import Job, Repo

        job = (await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))).scalar_one_or_none()
        if job is None:
            return "unavailable"
        repo = (await session.execute(select(Repo).where(Repo.id == job.repo_id))).scalar_one()
        if repo.installation_id is None:
            return "not_publish_capable"
        art = (
            await session.execute(
                select(Artifact).where(
                    Artifact.job_id == job.id, Artifact.kind == ArtifactKind.BUNDLE
                )
            )
        ).scalar_one_or_none()
        if art is None:
            return "no_bundle"
        store = await load_db_approval_store(session, job_id)
        bundle = _bundle_from_artifact(json.loads(art.content), repo.installation_id)

    minter = settings_token_minter(settings, now=int(datetime.now(UTC).timestamp()))
    try:
        pr = open_draft_pr_for_fix(bundle, store=store, token_minter=minter)
    except Exception as exc:  # ApprovalError or GitHub error
        log.warning("publish_failed", job_id=job_id, error=str(exc))
        return f"error: {exc}"

    async with db.session() as session:
        from app.models.entities import Job

        job = (await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))).scalar_one()
        job.cost = {**(job.cost or {}), "pr_url": pr.url, "pr_number": pr.number}
        await session.commit()
    log.info("pr_published", job_id=job_id, url=pr.url)
    return pr.url
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/workers/test_control_tasks.py -k publish -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/control_tasks.py tests/workers/test_control_tasks.py
git commit -m "feat(workers): publish_pr opens the approved draft PR from a bundle artifact"
```

---

### Task 12: `POST /jobs/{id}/publish` endpoint

**Files:**
- Modify: `app/api/jobs.py`
- Test: `tests/api/test_publish_api.py`

**Interfaces:**
- Consumes: live `Job` + `Repo`, `latest_decision`, `get_queue`, `JobQueue.enqueue_task`.
- Produces: `POST /jobs/{id}/publish` → 202 when it enqueues `publish_pr`. 409 if not approved (state != APPROVED) or repo not publish-capable.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_publish_api.py
import pytest


@pytest.mark.asyncio
async def test_publish_requires_approval(api_client, queue_stub):
    rid = (await api_client.post("/repos", json={"clone_url": "octo/demo"})).json()["id"]
    jid = (await api_client.post("/jobs", json={"repo_id": rid, "body": "x", "title": "t"})).json()["id"]
    r = await api_client.post(f"/jobs/{jid}/publish")
    assert r.status_code == 409  # not approved


@pytest.mark.asyncio
async def test_publish_enqueues_when_approved(api_client, queue_stub, approve_and_make_publishable):
    jid = await approve_and_make_publishable(api_client)  # sets repo.installation_id + APPROVED
    r = await api_client.post(f"/jobs/{jid}/publish")
    assert r.status_code == 202
    assert ("publish_pr", (jid,)) in [(t, a) for (t, a, _k) in queue_stub.tasks]
```

`approve_and_make_publishable` is a fixture/helper: create repo, set `installation_id` directly via a session, create job, drive it to AWAITING_APPROVAL then `POST /jobs/{id}/approve`. Build it in `tests/api/conftest.py` reusing the existing approve route.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_publish_api.py -v`
Expected: FAIL — publish route 404/405.

- [ ] **Step 3: Implement** (add to `app/api/jobs.py`)

```python
@router.post("/jobs/{job_id}/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    queue: object | None = Depends(get_queue),
) -> dict[str, str]:
    job_uuid = _parse_job_id(job_id)
    job = (await session.execute(select(Job).where(Job.id == job_uuid))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if job.state is not JobState.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "approval required before publishing")
    repo = (await session.execute(select(Repo).where(Repo.id == job.repo_id))).scalar_one()
    if repo.installation_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "connect GitHub App before publishing")

    from app.workers.queue import JobQueue

    if not isinstance(queue, JobQueue):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "worker queue not configured")
    await queue.enqueue_task("publish_pr", job_id, dedup_key=f"publish:{job_id}")
    return {"status": "publishing", "job_id": job_id}
```

Add `Repo` to the entities import at the top of `app/api/jobs.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_publish_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/jobs.py tests/api/test_publish_api.py tests/api/conftest.py
git commit -m "feat(api): POST /jobs/{id}/publish — gated draft-PR publish from UI"
```

---

## Milestone E — Frontend

### Task 13: API client + types

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/types.ts`
- Test: `frontend/src/__tests__/api.test.ts` (extend)

**Interfaces:**
- Produces TS functions: `listRepos()`, `addRepo(cloneUrl)`, `deleteRepo(id)`, `connectRepo(id)`, `scanRepo(id)`, `createJob(repoId, body, title?)`, `publishJob(id)`; `Repo` type `{id, full_name, publish_capable, created_at}`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/api.test.ts (append)
import { addRepo, createJob } from "../api";

it("addRepo posts clone_url", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: "r1", full_name: "octo/demo", publish_capable: false, created_at: "" }),
      { status: 201, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  const repo = await addRepo("octo/demo");
  expect(repo.full_name).toBe("octo/demo");
  expect(fetchMock).toHaveBeenCalledWith("/repos", expect.objectContaining({ method: "POST" }));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/api.test.ts`
Expected: FAIL — `addRepo` not exported.

- [ ] **Step 3: Implement** — add the `Repo` type to `types.ts`:

```ts
export interface Repo {
  id: string;
  full_name: string;
  publish_capable: boolean;
  created_at: string;
}
```

And append to `api.ts`:

```ts
import type { Repo } from "./types";

export function listRepos(): Promise<Repo[]> {
  return request<Repo[]>("/repos");
}
export function addRepo(cloneUrl: string): Promise<Repo> {
  return request<Repo>("/repos", { method: "POST", body: JSON.stringify({ clone_url: cloneUrl }) });
}
export function deleteRepo(id: string): Promise<void> {
  return request<void>(`/repos/${id}`, { method: "DELETE" });
}
export function connectRepo(id: string): Promise<{ status: string }> {
  return request(`/repos/${id}/connect`, { method: "POST" });
}
export function scanRepo(id: string): Promise<{ status: string }> {
  return request(`/repos/${id}/scan`, { method: "POST" });
}
export function createJob(repoId: string, body: string, title?: string): Promise<Job> {
  return request<Job>("/jobs", { method: "POST", body: JSON.stringify({ repo_id: repoId, body, title }) });
}
export function publishJob(id: string): Promise<{ status: string }> {
  return request(`/jobs/${id}/publish`, { method: "POST" });
}
```

Note: `request<void>` for DELETE — guard the `resp.json()` parse for 204 (no body). If `request` always parses JSON, add `if (resp.status === 204) return undefined as T;` before the parse in `request`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/api.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/types.ts frontend/src/__tests__/api.test.ts
git commit -m "feat(ui): api client for repos, manual jobs, publish"
```

---

### Task 14: Repos tab

**Files:**
- Create: `frontend/src/components/RepoList.tsx`
- Modify: `frontend/src/App.tsx` (add `"repos"` to the `Tab` union + nav + panel)
- Test: `frontend/src/__tests__/RepoList.test.tsx`

**Interfaces:**
- Consumes: `listRepos`, `addRepo`, `deleteRepo`, `connectRepo`, `scanRepo`.
- Produces: `<RepoList />` — add-by-URL input, list with a publish-capable badge, per-row Scan / Connect (only when not publish-capable) / Delete buttons.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/RepoList.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RepoList } from "../components/RepoList";
import * as api from "../api";
import { vi } from "vitest";

it("lists repos and adds one", async () => {
  vi.spyOn(api, "listRepos").mockResolvedValue([
    { id: "r1", full_name: "octo/demo", publish_capable: false, created_at: "" },
  ]);
  const add = vi.spyOn(api, "addRepo").mockResolvedValue(
    { id: "r2", full_name: "octo/new", publish_capable: false, created_at: "" });
  render(<RepoList />);
  await screen.findByText("octo/demo");
  await userEvent.type(screen.getByPlaceholderText(/github.com/i), "octo/new");
  await userEvent.click(screen.getByRole("button", { name: /add repo/i }));
  await waitFor(() => expect(add).toHaveBeenCalledWith("octo/new"));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/RepoList.test.tsx`
Expected: FAIL — `RepoList` does not exist.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/RepoList.tsx
import { useCallback, useEffect, useState } from "react";
import { addRepo, connectRepo, deleteRepo, listRepos, scanRepo } from "../api";
import type { Repo } from "../types";

export function RepoList() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setRepos(await listRepos()); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "failed to load repos"); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const onAdd = async () => {
    if (!url.trim()) return;
    try { await addRepo(url.trim()); setUrl(""); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "add failed"); }
  };

  return (
    <div className="p-6">
      <div className="mb-4 flex gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/name"
          className="flex-1 rounded border border-slate-300 px-3 py-1 text-sm"
        />
        <button type="button" onClick={onAdd}
          className="rounded bg-slate-800 px-3 py-1 text-sm font-medium text-white">
          Add repo
        </button>
      </div>
      {error && <p className="mb-2 text-sm text-rose-700">{error}</p>}
      <ul className="divide-y divide-slate-200">
        {repos.map((r) => (
          <li key={r.id} className="flex items-center justify-between py-2">
            <span className="text-sm font-medium">{r.full_name}</span>
            <span className="flex items-center gap-2 text-xs">
              <span className={r.publish_capable ? "text-emerald-600" : "text-slate-400"}>
                {r.publish_capable ? "publish-capable" : "fix-only"}
              </span>
              <button type="button" onClick={() => scanRepo(r.id)}
                className="rounded bg-slate-100 px-2 py-1">Scan</button>
              {!r.publish_capable && (
                <button type="button" onClick={() => connectRepo(r.id)}
                  className="rounded bg-slate-100 px-2 py-1">Connect GitHub App</button>
              )}
              <button type="button" onClick={async () => { await deleteRepo(r.id); await refresh(); }}
                className="rounded bg-rose-50 px-2 py-1 text-rose-700">Delete</button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 4: Wire the tab in `App.tsx`**

Change `type Tab = "jobs" | "findings";` → `type Tab = "jobs" | "findings" | "repos";`, add `"repos"` to the nav `.map` array, give it the label `"Repos"`, and render `<RepoList />` when `tab === "repos"`. Import `RepoList`.

- [ ] **Step 5: Run test + typecheck**

Run: `cd frontend && npx vitest run src/__tests__/RepoList.test.tsx && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/RepoList.tsx frontend/src/App.tsx frontend/src/__tests__/RepoList.test.tsx
git commit -m "feat(ui): Repos tab — add, scan, connect, delete"
```

---

### Task 15: New Fix modal

**Files:**
- Create: `frontend/src/components/NewFixModal.tsx`
- Modify: `frontend/src/App.tsx` (a "+ New Fix" button on the Jobs tab that opens it; on success select the new job)
- Test: `frontend/src/__tests__/NewFixModal.test.tsx`

**Interfaces:**
- Consumes: `listRepos`, `createJob`.
- Produces: `<NewFixModal onCreated={(job) => void} onClose={() => void} />` — repo `<select>`, textarea, optional title, Submit calls `createJob` then `onCreated`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/NewFixModal.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NewFixModal } from "../components/NewFixModal";
import * as api from "../api";
import { vi } from "vitest";

it("submits a new fix", async () => {
  vi.spyOn(api, "listRepos").mockResolvedValue([
    { id: "r1", full_name: "octo/demo", publish_capable: false, created_at: "" },
  ]);
  const create = vi.spyOn(api, "createJob").mockResolvedValue({ id: "j1" } as never);
  const onCreated = vi.fn();
  render(<NewFixModal onCreated={onCreated} onClose={() => {}} />);
  await screen.findByText("octo/demo");
  await userEvent.type(screen.getByPlaceholderText(/issue text/i), "boom");
  await userEvent.click(screen.getByRole("button", { name: /submit/i }));
  expect(create).toHaveBeenCalledWith("r1", "boom", "");
  expect(onCreated).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/NewFixModal.test.tsx`
Expected: FAIL — `NewFixModal` does not exist.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/NewFixModal.tsx
import { useEffect, useState } from "react";
import { createJob, listRepos } from "../api";
import type { Job, Repo } from "../types";

export function NewFixModal({ onCreated, onClose }: {
  onCreated: (job: Job) => void;
  onClose: () => void;
}) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState("");
  const [body, setBody] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listRepos().then((rs) => { setRepos(rs); if (rs[0]) setRepoId(rs[0].id); });
  }, []);

  const submit = async () => {
    if (!repoId || !body.trim()) { setError("pick a repo and enter issue text"); return; }
    try { onCreated(await createJob(repoId, body, title)); }
    catch (e) { setError(e instanceof Error ? e.message : "submit failed"); }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-black/30" role="dialog">
      <div className="w-[32rem] rounded bg-white p-6 shadow-lg">
        <h2 className="mb-3 text-lg font-bold">New Fix</h2>
        <select value={repoId} onChange={(e) => setRepoId(e.target.value)}
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm">
          {repos.map((r) => <option key={r.id} value={r.id}>{r.full_name}</option>)}
        </select>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="title (optional)"
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm" />
        <textarea value={body} onChange={(e) => setBody(e.target.value)}
          placeholder="issue text or stack trace" rows={8}
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs" />
        {error && <p className="mb-2 text-sm text-rose-700">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded bg-slate-100 px-3 py-1 text-sm">Cancel</button>
          <button type="button" onClick={submit}
            className="rounded bg-slate-800 px-3 py-1 text-sm font-medium text-white">Submit</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire into `App.tsx`**

Add `const [showNew, setShowNew] = useState(false);`. On the Jobs tab, render a "+ New Fix" button (e.g. above `JobList`) that sets `showNew(true)`. When `showNew`, render `<NewFixModal onClose={() => setShowNew(false)} onCreated={(job) => { setShowNew(false); void refreshJobs(); setSelectedId(job.id); }} />`.

- [ ] **Step 5: Run test + typecheck**

Run: `cd frontend && npx vitest run src/__tests__/NewFixModal.test.tsx && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/NewFixModal.tsx frontend/src/App.tsx frontend/src/__tests__/NewFixModal.test.tsx
git commit -m "feat(ui): New Fix modal — submit a job from the browser"
```

---

### Task 16: Publish button on JobDetail

**Files:**
- Modify: `frontend/src/components/JobDetail.tsx`
- Test: `frontend/src/__tests__/JobDetail.test.tsx` (extend)

**Interfaces:**
- Consumes: `publishJob`, the job's `state` and its repo capability. `JobView` does not currently carry repo capability — add `repo_full_name` and `publish_capable` to the `JobView`/`/jobs/{id}` response (Task 8/jobs.py) and the `Job` TS type, so the button can gate on it. (Small addition: in `_load_job_view`, include the repo's `full_name` + `installation_id is not None`.)
- Produces: a "Publish draft PR" button shown only when `job.state === "approved"` && `job.publish_capable`; on click calls `publishJob(id)` and shows a "publishing…" / PR-url state.

- [ ] **Step 1: Extend the backend view** (small, do first)

In `app/api/jobs.py` `JobView`, add `repo_full_name: str` and `publish_capable: bool`; populate them in `_load_job_view` by loading the job's repo. Add a quick assertion to `tests/api/test_publish_api.py`:

```python
@pytest.mark.asyncio
async def test_job_view_has_capability(api_client):
    rid = (await api_client.post("/repos", json={"clone_url": "octo/demo"})).json()["id"]
    jid = (await api_client.post("/jobs", json={"repo_id": rid, "body": "x", "title": "t"})).json()["id"]
    j = (await api_client.get(f"/jobs/{jid}")).json()
    assert j["repo_full_name"] == "octo/demo"
    assert j["publish_capable"] is False
```

Run: `pytest tests/api/test_publish_api.py::test_job_view_has_capability -v` → make it pass, then add the fields to the `Job` TS type in `types.ts`.

- [ ] **Step 2: Write the failing UI test**

```tsx
// frontend/src/__tests__/JobDetail.test.tsx (append)
import { vi } from "vitest";
import * as api from "../api";

it("shows Publish only when approved + capable", async () => {
  const pub = vi.spyOn(api, "publishJob").mockResolvedValue({ status: "publishing" });
  const job = { id: "j1", state: "approved", publish_capable: true, repo_full_name: "octo/demo",
    runs: [], fix: null, cost: {}, cost_usd: 0, created_at: "", updated_at: "",
    gh_issue_number: null, issue_title: "t", failure_reason: null } as never;
  render(<JobDetail job={job} onDecision={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: /publish draft pr/i }));
  expect(pub).toHaveBeenCalledWith("j1");
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/JobDetail.test.tsx`
Expected: FAIL — no Publish button.

- [ ] **Step 4: Implement** — in `JobDetail.tsx`, add near the approve/reject controls:

```tsx
{job.state === "approved" && job.publish_capable && (
  <button type="button"
    onClick={async () => { setPublishing(true); try { await publishJob(job.id); } finally { setPublishing(false); } }}
    disabled={publishing}
    className="rounded bg-emerald-600 px-3 py-1 text-sm font-medium text-white disabled:opacity-50">
    {publishing ? "Publishing…" : "Publish draft PR"}
  </button>
)}
```

Add `const [publishing, setPublishing] = useState(false);` and `import { publishJob } from "../api";`. If the job's `cost.pr_url` is present, render it as a link instead of the button.

- [ ] **Step 5: Run test + typecheck**

Run: `cd frontend && npx vitest run src/__tests__/JobDetail.test.tsx && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 6: Commit**

```bash
git add app/api/jobs.py frontend/src/components/JobDetail.tsx frontend/src/types.ts frontend/src/__tests__/JobDetail.test.tsx tests/api/test_publish_api.py
git commit -m "feat(ui): Publish draft PR button on JobDetail (gated on approved + capable)"
```

---

## Final verification

- [ ] **Backend:** `ruff check && ruff format --check && mypy app && pytest -q`
- [ ] **Frontend:** `cd frontend && npx vitest run && npx tsc --noEmit && npm run build`
- [ ] **Migration:** `alembic upgrade head && alembic check` clean.
- [ ] **Manual smoke (worker + redis + api + vite running):** add a public repo → New Fix with a stack trace → watch it run live → approve → (after Connect) Publish → PR URL appears. Scan a repo → findings show in the Findings tab.

## Self-review notes

- **Spec coverage:** all four features mapped — repos (Tasks 2,6,14), New Fix (7,8,15), scan (5,6,14), publish (9,10,11,12,16); migration (1); safety boundary preserved (worker tasks 4/5/11 own all GitHub I/O; publish goes through `assert_approved` in Task 11; manual body stored as artifact in Task 7). Non-goal (no auth, localhost) recorded in Global Constraints.
- **Open implementation detail flagged, not hand-waved:** `resolve_repo_installation` (Task 4) may not yet exist in `app/vcs/auth.py`; the task instructs reading that file and reusing its JWT primitives. The `ApprovalStore` key format (Task 10) must match `assert_approved` — the task says to verify against `app/vcs/approval.py`.
- **Type consistency:** `installation_id is not None` is the single publish-capability signal everywhere (model, RepoView.publish_capable, JobView.publish_capable, publish_pr guard, endpoint guard). Bundle JSON shape in Task 9 matches `_bundle_from_artifact` in Task 11 and the CLI's `_bundle_from_json`.
