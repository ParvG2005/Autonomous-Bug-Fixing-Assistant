"""Orchestrate a full scan against the database (Phase 13).

Ties the pure pieces together: :func:`scan_repo` (detectors) → :func:`triage`
(dedup + budget cap) → persistence (:mod:`app.db.discovery`). Shared by the
``bugfix-scan`` CLI and the dashboard's promote action so there is one scan path.

Cost control lives here: when ``promote`` is False (the spend gate is not
confirmed) the effective job budget is zero — candidates are still recorded as
findings so the dashboard can show them, but **no token-spending job is created**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.discovery import (
    create_scan,
    finish_scan,
    known_fingerprints,
    promote_candidate,
    save_finding,
)
from app.db.session import Database
from app.discovery.scan import scan_repo
from app.discovery.sources import DEFAULT_DETECTORS
from app.discovery.sources.base import Detector
from app.discovery.triage import triage
from app.models.entities import FindingStatus, Repo, ScanState, ScanTrigger
from app.sandbox.base import Sandbox
from app.sandbox.models import ResourceLimits
from app.telemetry.logging import get_logger

log = get_logger("discovery.service")


@dataclass
class ScanSummary:
    """What a scan did, for the CLI/API to report."""

    scan_id: str
    sources_run: list[str] = field(default_factory=list)
    candidates: int = 0
    promoted_job_ids: list[str] = field(default_factory=list)
    parked: int = 0
    duplicates: int = 0
    errors: dict[str, str] = field(default_factory=dict)


async def _resolve_repo_id(session: AsyncSession, full_name: str) -> object:
    repo = (
        await session.execute(select(Repo).where(Repo.full_name == full_name))
    ).scalar_one_or_none()
    if repo is None:
        raise ValueError(
            f"repo {full_name!r} is not registered — install the GitHub App or run "
            "bugfix-bootstrap --scrape first"
        )
    return repo.id


async def run_scan(
    db: Database,
    repo_full_name: str,
    workspace: Path,
    *,
    detectors: list[Detector] | None = None,
    sandbox: Sandbox,
    limits: ResourceLimits | None = None,
    trigger: ScanTrigger = ScanTrigger.MANUAL,
    max_jobs: int = 5,
    promote: bool = False,
) -> ScanSummary:
    """Scan ``workspace`` for ``repo_full_name``, persist findings, optionally promote.

    Detectors run synchronously (sandboxed); only the persistence is awaited. The
    spend gate is ``promote``: without it, the effective budget is zero jobs.
    """
    detectors = detectors if detectors is not None else DEFAULT_DETECTORS
    scan_out = scan_repo(workspace, detectors, sandbox=sandbox, limits=limits)
    effective_max = max_jobs if promote else 0

    async with db.session() as session:
        repo_id = await _resolve_repo_id(session, repo_full_name)
        scan = await create_scan(session, repo_id, trigger=trigger, budget={"max_jobs": max_jobs})
        known = await known_fingerprints(session, repo_id)
        verdict = triage(scan_out.candidates, known_fingerprints=known, max_jobs=effective_max)

        summary = ScanSummary(
            scan_id=str(scan.id),
            sources_run=scan_out.sources_run,
            candidates=len(scan_out.candidates),
            parked=len(verdict.park),
            duplicates=len(verdict.duplicates),
            errors=scan_out.errors,
        )
        for cand in verdict.promote:
            _, job = await promote_candidate(session, scan, cand)
            summary.promoted_job_ids.append(str(job.id))
        for cand in verdict.park:
            await save_finding(session, scan, cand, status=FindingStatus.CANDIDATE)
        await finish_scan(session, scan, sources_run=scan_out.sources_run, state=ScanState.DONE)

    log.info(
        "scan_done",
        repo=repo_full_name,
        candidates=summary.candidates,
        promoted=len(summary.promoted_job_ids),
        parked=summary.parked,
        duplicates=summary.duplicates,
    )
    return summary
