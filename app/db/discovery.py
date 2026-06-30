"""Persistence for proactive discovery (Phase 13).

The seam to the existing flow is the whole trick: :func:`promote_candidate`
converts a :class:`~app.discovery.finding.Candidate` into the **same artifact +
queued JOB the webhook produces** — only the ``trigger`` (``discovery``) and a
``finding_id`` backref differ. From there ``solve_issue``, the worker pipeline,
the guardrails, and the human gate all apply with zero changes.

Untrusted scanner/stacktrace text is stored on the FINDING (``evidence``) and,
for a promoted candidate, in an ISSUE_BODY artifact — never inlined on the hot
JOB row, exactly like a webhook issue.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.finding import Candidate
from app.models.entities import (
    Artifact,
    ArtifactKind,
    ArtifactStorage,
    Finding,
    FindingStatus,
    Job,
    JobState,
    JobTrigger,
    Scan,
    ScanState,
    ScanTrigger,
)

_DEFAULT_BUDGET = {"max_iterations": 20, "max_tokens": 400_000, "deadline_s": 600.0}


async def create_scan(
    session: AsyncSession,
    repo_id: object,
    *,
    trigger: ScanTrigger = ScanTrigger.MANUAL,
    budget: dict[str, object] | None = None,
) -> Scan:
    """Open a running SCAN row for ``repo_id``."""
    scan = Scan(
        repo_id=repo_id,
        trigger=trigger,
        state=ScanState.RUNNING,
        sources_run=[],
        budget=dict(budget or {}),
    )
    session.add(scan)
    await session.flush()
    return scan


async def finish_scan(
    session: AsyncSession, scan: Scan, *, sources_run: list[str], state: ScanState
) -> None:
    scan.sources_run = list(sources_run)
    scan.state = state
    await session.flush()


async def known_fingerprints(session: AsyncSession, repo_id: object) -> set[str]:
    """Every fingerprint already recorded for ``repo_id`` — the dedup baseline.

    A re-scan checks new candidates against this set so a known finding is never
    refiled (the acceptance test's "re-scan does not refile" guarantee).
    """
    rows = (
        (await session.execute(select(Finding.fingerprint).where(Finding.repo_id == repo_id)))
        .scalars()
        .all()
    )
    return set(rows)


async def save_finding(
    session: AsyncSession,
    scan: Scan,
    candidate: Candidate,
    *,
    status: FindingStatus = FindingStatus.CANDIDATE,
) -> Finding:
    """Persist a candidate as a FINDING row (unique per repo by fingerprint)."""
    finding = Finding(
        scan_id=scan.id,
        repo_id=scan.repo_id,
        source=candidate.source,
        fingerprint=candidate.fingerprint(),
        summary=candidate.summary,
        evidence=candidate.evidence,
        frames=[{"file": f.file, "line": f.line, "function": f.function} for f in candidate.frames],
        confidence=candidate.confidence,
        severity=candidate.severity,
        status=status,
    )
    session.add(finding)
    await session.flush()
    return finding


async def promote_candidate(
    session: AsyncSession,
    scan: Scan,
    candidate: Candidate,
) -> tuple[Finding, Job]:
    """Persist ``candidate`` as a FINDING and enqueue a discovery JOB for it.

    Mirrors :func:`app.db.jobs.ingest_labeled_issue`: the rendered issue body is
    stored as an ISSUE_BODY artifact and the job references it; the job is left
    ``queued`` for the worker, with ``trigger=discovery`` and a ``finding_id``
    backref for provenance.
    """
    finding = await save_finding(session, scan, candidate, status=FindingStatus.CANDIDATE)

    title, body = candidate.render_issue()
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
        repo_id=scan.repo_id,
        gh_issue_number=None,
        finding_id=finding.id,
        trigger=JobTrigger.DISCOVERY,
        issue_title=title,
        state=JobState.QUEUED,
        budget=dict(_DEFAULT_BUDGET),
        cost={},
    )
    session.add(job)
    await session.flush()  # assign job.id

    artifact.job_id = job.id
    session.add(artifact)
    await session.flush()

    job.issue_body_ref = artifact.id
    finding.status = FindingStatus.PROMOTED
    finding.job_id = job.id
    await session.flush()

    return finding, job


async def promote_finding(session: AsyncSession, finding: Finding) -> Job:
    """Promote an already-persisted (parked) FINDING to a queued discovery JOB.

    The dashboard's "promote to job" action (§9 — a human gate at discovery too).
    Idempotent-ish: a finding already promoted just returns its existing job.
    """
    from app.discovery.promote import finding_to_candidate

    if finding.status is FindingStatus.PROMOTED and finding.job_id is not None:
        existing = (
            await session.execute(select(Job).where(Job.id == finding.job_id))
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    candidate = finding_to_candidate(finding)
    title, body = candidate.render_issue()
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
        repo_id=finding.repo_id,
        gh_issue_number=None,
        finding_id=finding.id,
        trigger=JobTrigger.DISCOVERY,
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
    finding.status = FindingStatus.PROMOTED
    finding.job_id = job.id
    await session.flush()
    return job
