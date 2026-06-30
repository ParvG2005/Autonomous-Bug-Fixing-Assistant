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

from app.models.entities import Repo
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
    raise NotImplementedError  # Task 5


async def publish_pr(ctx: dict[str, Any], job_id: str) -> str:
    raise NotImplementedError  # Task 8
