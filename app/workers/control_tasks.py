"""Worker tasks for the UI control plane: GitHub I/O kept off the API process.

``connect_repo`` / ``scan_repo`` / ``publish_pr`` are enqueued by the API and run
here where network + token minting are allowed (SECURITY.md C4).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from sqlalchemy import select

from app.discovery.service import run_scan
from app.discovery.sources import DEFAULT_DETECTORS
from app.index.clone import clone_repo
from app.models.entities import Repo, ScanTrigger
from app.sandbox import get_sandbox
from app.telemetry.logging import get_logger

log = get_logger("workers.control")


async def _resolve_installation(settings: Any, full_name: str) -> tuple[int, int]:
    """Return ``(gh_repo_id, installation_id)`` for ``full_name`` via the GitHub App.

    Delegates to the synchronous ``app.vcs.auth.resolve_repo_installation`` off
    the event loop (it makes blocking ``httpx`` calls), so the worker loop is
    never blocked on GitHub I/O.
    """
    from app.vcs.auth import resolve_repo_installation

    return await asyncio.to_thread(
        resolve_repo_installation, settings, full_name, now=int(time.time())
    )


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
    await asyncio.to_thread(clone_repo, f"https://github.com/{full_name}.git", workspace, depth=1)
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


async def publish_pr(ctx: dict[str, Any], job_id: str) -> str:
    raise NotImplementedError  # Task 8
