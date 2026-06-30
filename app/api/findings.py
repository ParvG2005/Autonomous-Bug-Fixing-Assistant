"""Discovery read surface + the promote-to-job action (Phase 13 §9).

- ``GET /findings`` — recent findings (newest first), optionally per repo.
- ``GET /scans`` — recent scans and their state.
- ``POST /findings/{id}/promote`` — a human promotes a parked candidate; it
  enqueues a discovery job that then flows to the existing approve/draft-PR gate.

Promotion is the only mutating call here and it never touches GitHub — it just
files a job, keeping a human in the loop at discovery as well as at the fix gate.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_queue, get_session
from app.db.discovery import promote_finding
from app.models.entities import Finding, Scan
from app.telemetry.logging import get_logger

router = APIRouter(tags=["discovery"])
log = get_logger("api.findings")


class FindingView(BaseModel):
    id: str
    scan_id: str
    source: str
    summary: str
    severity: str
    confidence: float
    status: str
    job_id: str | None
    created_at: datetime


class ScanView(BaseModel):
    id: str
    state: str
    trigger: str
    sources_run: list[str]
    created_at: datetime


def _finding_view(f: Finding) -> FindingView:
    return FindingView(
        id=str(f.id),
        scan_id=str(f.scan_id),
        source=f.source.value,
        summary=f.summary,
        severity=f.severity,
        confidence=f.confidence,
        status=f.status.value,
        job_id=str(f.job_id) if f.job_id else None,
        created_at=f.created_at,
    )


@router.get("/findings", response_model=list[FindingView])
async def list_findings(
    limit: int = 100, session: AsyncSession = Depends(get_session)
) -> list[FindingView]:
    limit = max(1, min(limit, 500))
    rows = (
        (await session.execute(select(Finding).order_by(Finding.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [_finding_view(f) for f in rows]


@router.get("/scans", response_model=list[ScanView])
async def list_scans(
    limit: int = 50, session: AsyncSession = Depends(get_session)
) -> list[ScanView]:
    limit = max(1, min(limit, 200))
    rows = (
        (await session.execute(select(Scan).order_by(Scan.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [
        ScanView(
            id=str(s.id),
            state=s.state.value,
            trigger=s.trigger.value,
            sources_run=list(s.sources_run or []),
            created_at=s.created_at,
        )
        for s in rows
    ]


@router.post("/findings/{finding_id}/promote", response_model=FindingView)
async def promote(
    finding_id: str,
    session: AsyncSession = Depends(get_session),
    queue: object | None = Depends(get_queue),
) -> FindingView:
    """Promote a finding to a queued discovery job (human gate at discovery)."""
    try:
        fid = uuid.UUID(finding_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed finding id") from exc

    finding = (await session.execute(select(Finding).where(Finding.id == fid))).scalar_one_or_none()
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finding not found")

    job = await promote_finding(session, finding)
    await session.commit()

    if queue is not None:
        from app.workers.queue import JobQueue

        if isinstance(queue, JobQueue):
            await queue.enqueue(job.id)

    log.info("finding_promoted", finding_id=finding_id, job_id=str(job.id))
    view: dict[str, Any] = _finding_view(finding).model_dump()
    return FindingView(**view)
