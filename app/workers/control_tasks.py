"""Worker tasks for the UI control plane: GitHub I/O kept off the API process.

``connect_repo`` / ``scan_repo`` / ``publish_pr`` are enqueued by the API and run
here where network + token minting are allowed (SECURITY.md C4).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db.repos import repo_clone_url
from app.discovery.service import run_scan
from app.discovery.sources import DEFAULT_DETECTORS
from app.index.clone import clone_repo
from app.models.entities import Artifact, ArtifactKind, Job, Repo, ScanTrigger
from app.sandbox import get_sandbox
from app.telemetry.logging import get_logger
from app.vcs.auth import settings_token_minter
from app.vcs.db_store import load_db_approval_store
from app.vcs.models import FileChange, FixBundle, RepoRef
from app.vcs.publish import open_draft_pr_for_fix

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
        clone_url = repo_clone_url(repo)
    workspace = (settings.workspace_root / f"scan-{repo_id}").resolve()
    await asyncio.to_thread(clone_repo, clone_url, workspace, depth=1)
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


def _bundle_from_artifact(raw: dict[str, Any], installation_id: int) -> FixBundle:
    repo = RepoRef(
        owner=raw["repo"]["owner"], name=raw["repo"]["name"], installation_id=installation_id
    )
    return FixBundle(
        job_id=raw["job_id"],
        repo=repo,
        base_branch=raw["base_branch"],
        head_branch=raw["head_branch"],
        title=raw["title"],
        commit_message=raw["commit_message"],
        body=raw["body"],
        changes=[FileChange(**c) for c in raw["changes"]],
        reasoning_comment=raw.get("reasoning_comment", ""),
    )


async def publish_pr(ctx: dict[str, Any], job_id: str) -> str:
    """Open the approved draft PR for ``job_id`` from its stored BUNDLE artifact.

    Rebuilds the :class:`~app.vcs.models.FixBundle` with the *live*
    ``Repo.installation_id`` (never the value frozen into the artifact at fix
    time), then delegates to :func:`~app.vcs.publish.open_draft_pr_for_fix`,
    which asserts approval before minting any token (SECURITY.md C1/C4).
    """
    db = ctx["db"]
    settings = ctx["settings"]
    async with db.session() as session:
        job = (
            await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
        ).scalar_one_or_none()
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
        job = (await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))).scalar_one()
        job.cost = {**(job.cost or {}), "pr_url": pr.url, "pr_number": pr.number}
        job.failure_reason = None
        await session.commit()
    log.info("pr_published", job_id=job_id, url=pr.url)
    return pr.url
