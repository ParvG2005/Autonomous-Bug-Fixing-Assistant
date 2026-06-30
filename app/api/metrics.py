"""Fleet metrics endpoint (Phase 10).

``GET /metrics`` aggregates the headline numbers — resolve rate, regression rate,
mean time-to-fix, and cost-per-fix — over jobs that produced a fix attempt. The
math lives in :mod:`app.telemetry.metrics`; this module only maps ORM rows onto
:class:`~app.telemetry.metrics.JobOutcome` value objects.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.models.entities import Fix, Job
from app.telemetry.metrics import JobOutcome, compute_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def get_metrics(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Aggregate metrics over every job that reached a fix attempt."""
    fixes = (await session.execute(select(Fix))).scalars().all()
    jobs = {j.id: j for j in (await session.execute(select(Job))).scalars().all()}

    outcomes: list[JobOutcome] = []
    for fix in fixes:
        job = jobs.get(fix.job_id)
        if job is None:
            continue
        cost = job.cost or {}
        duration = (job.updated_at - job.created_at).total_seconds() if job.updated_at else 0.0
        outcomes.append(
            JobOutcome(
                resolved=fix.tests_pass,
                edited=(fix.diff_lines_added + fix.diff_lines_removed) > 0,
                cost_usd=float(cost.get("cost_usd", 0.0) or 0.0),
                duration_s=max(duration, 0.0),
            )
        )

    return compute_metrics(outcomes).as_dict()
