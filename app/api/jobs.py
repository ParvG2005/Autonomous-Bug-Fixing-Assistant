"""Job status + live-log endpoints (Phase 7).

Read-only control-plane surface over the job lifecycle:

- ``GET /jobs`` — recent jobs (newest first).
- ``GET /jobs/{job_id}`` — one job's full status: state, cost, per-phase runs,
  and the proposed fix summary (no diff body — that is an artifact).
- ``GET /jobs/{job_id}/logs`` — Server-Sent Events: replays the job's progress
  log, then streams new lines until the job reaches a terminal state.

It also owns the C1 human gate: ``POST /jobs/{id}/approve`` and ``/reject``
*do* mutate — they append an immutable approval decision and drive the state
machine, but never touch GitHub (the draft-PR publish stays behind
``bugfix-pr open --confirm``). ``GET /jobs/{id}/artifacts/{kind}`` serves the
diff / reasoning / trace bodies the dashboard renders.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_session
from app.db.approvals import record_decision
from app.db.session import Database
from app.models.entities import (
    ApprovalDecision,
    Artifact,
    ArtifactKind,
    Fix,
    Job,
    JobState,
    Run,
)
from app.workers.progress import read_logs
from app.workers.state import TERMINAL_STATES, InvalidTransition, transition

router = APIRouter(tags=["jobs"])

#: Artifact kinds the dashboard may fetch. ``log`` is streamed via SSE and
#: ``issue_body`` is untrusted user input — neither is served here.
_FETCHABLE_ARTIFACTS = {
    ArtifactKind.DIFF,
    ArtifactKind.REASONING,
    ArtifactKind.TRACE,
}

_SSE_POLL_S = 0.5
_SSE_MAX_TICKS = 1200  # ~10 min ceiling on a single log stream


class RunView(BaseModel):
    phase: str
    status: str
    attempt: int
    metrics: dict[str, Any]


class FixView(BaseModel):
    diff_lines_added: int
    diff_lines_removed: int
    wrote_repro_test: bool
    tests_pass: bool
    flags: dict[str, Any]


class JobView(BaseModel):
    id: str
    state: str
    gh_issue_number: int | None
    issue_title: str | None
    failure_reason: str | None
    cost: dict[str, Any]
    cost_usd: float
    created_at: datetime
    updated_at: datetime
    runs: list[RunView]
    fix: FixView | None


class DecisionBody(BaseModel):
    actor: str = "dashboard"
    note: str | None = None


class ArtifactView(BaseModel):
    kind: str
    content: str


def _parse_job_id(job_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed job id") from exc


async def _load_job_view(session: AsyncSession, job_uuid: uuid.UUID) -> JobView:
    job = (await session.execute(select(Job).where(Job.id == job_uuid))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")

    runs = (
        (
            await session.execute(
                select(Run).where(Run.job_id == job_uuid).order_by(Run.started_at, Run.id)
            )
        )
        .scalars()
        .all()
    )
    fix = (
        (await session.execute(select(Fix).where(Fix.job_id == job_uuid).order_by(Fix.created_at)))
        .scalars()
        .first()
    )

    return JobView(
        id=str(job.id),
        state=job.state.value,
        gh_issue_number=job.gh_issue_number,
        issue_title=job.issue_title,
        failure_reason=job.failure_reason,
        cost=job.cost or {},
        cost_usd=float((job.cost or {}).get("cost_usd", 0.0) or 0.0),
        created_at=job.created_at,
        updated_at=job.updated_at,
        runs=[
            RunView(
                phase=r.phase.value,
                status=r.status.value,
                attempt=r.attempt,
                metrics=r.metrics or {},
            )
            for r in runs
        ],
        fix=(
            FixView(
                diff_lines_added=fix.diff_lines_added,
                diff_lines_removed=fix.diff_lines_removed,
                wrote_repro_test=fix.wrote_repro_test,
                tests_pass=fix.tests_pass,
                flags=fix.flags or {},
            )
            if fix is not None
            else None
        ),
    )


@router.get("/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> JobView:
    return await _load_job_view(session, _parse_job_id(job_id))


@router.get("/jobs", response_model=list[JobView])
async def list_jobs(limit: int = 50, session: AsyncSession = Depends(get_session)) -> list[JobView]:
    limit = max(1, min(limit, 200))
    rows = (
        (await session.execute(select(Job).order_by(Job.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [await _load_job_view(session, job.id) for job in rows]


async def _decide(
    job_id: str,
    body: DecisionBody | None,
    decision: ApprovalDecision,
    to_state: JobState,
    session: AsyncSession,
) -> JobView:
    """Record a human decision (C1) and drive the job state machine.

    Legal only from ``awaiting_approval``; any other state is a 409 and no
    approval row is written. No remote write happens here.
    """
    body = body or DecisionBody()
    job_uuid = _parse_job_id(job_id)
    job = (await session.execute(select(Job).where(Job.id == job_uuid))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    try:
        transition(job, to_state)
    except InvalidTransition as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"job is {exc.frm.value!r}; only an awaiting_approval job can be decided",
        ) from exc
    await record_decision(session, job_uuid, decision, actor=body.actor, note=body.note)
    return await _load_job_view(session, job_uuid)


@router.post("/jobs/{job_id}/approve", response_model=JobView)
async def approve_job(
    job_id: str,
    body: DecisionBody | None = None,
    session: AsyncSession = Depends(get_session),
) -> JobView:
    return await _decide(job_id, body, ApprovalDecision.APPROVED, JobState.APPROVED, session)


@router.post("/jobs/{job_id}/reject", response_model=JobView)
async def reject_job(
    job_id: str,
    body: DecisionBody | None = None,
    session: AsyncSession = Depends(get_session),
) -> JobView:
    return await _decide(job_id, body, ApprovalDecision.REJECTED, JobState.REJECTED, session)


@router.get("/jobs/{job_id}/artifacts/{kind}", response_model=ArtifactView)
async def get_artifact(
    job_id: str, kind: str, session: AsyncSession = Depends(get_session)
) -> ArtifactView:
    job_uuid = _parse_job_id(job_id)
    try:
        artifact_kind = ArtifactKind(kind)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown artifact kind {kind!r}") from exc
    if artifact_kind not in _FETCHABLE_ARTIFACTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"artifact kind {kind!r} is not fetchable")
    artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == job_uuid, Artifact.kind == artifact_kind)
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no {kind} artifact for this job")
    return ArtifactView(kind=artifact_kind.value, content=artifact.content or "")


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


async def _log_stream(db: Database, job_uuid: uuid.UUID) -> AsyncIterator[str]:
    """Replay then tail a job's progress log; close when the job is terminal."""
    seen: set[uuid.UUID] = set()
    for _ in range(_SSE_MAX_TICKS):
        async with db.session() as session:
            job = (
                await session.execute(select(Job).where(Job.id == job_uuid))
            ).scalar_one_or_none()
            if job is None:
                yield _sse("error", {"detail": "job not found"})
                return
            logs = await read_logs(session, job_uuid)
            state = job.state

        for artifact in logs:
            if artifact.id in seen:
                continue
            seen.add(artifact.id)
            yield _sse("log", {"message": artifact.content or ""})

        if state in TERMINAL_STATES or state is JobState.AWAITING_APPROVAL:
            yield _sse("state", {"state": state.value})
            return

        await asyncio.sleep(_SSE_POLL_S)


@router.get("/jobs/{job_id}/logs")
async def stream_job_logs(job_id: str, db: Database = Depends(get_db)) -> StreamingResponse:
    job_uuid = _parse_job_id(job_id)
    # 404 fast if the job is absent (don't open a stream for a non-existent job).
    async with db.session() as session:
        exists = (
            await session.execute(select(Job.id).where(Job.id == job_uuid))
        ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return StreamingResponse(_log_stream(db, job_uuid), media_type="text/event-stream")
