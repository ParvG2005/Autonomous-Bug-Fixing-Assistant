"""Crash recovery (Phase 7 acceptance: "recoverable on worker crash").

If a worker dies mid-run, its jobs are stranded in ``running`` with no live arq
task. On startup the worker sweeps them back to ``queued`` and re-enqueues, so
the pipeline runs again from a clean workspace. The pipeline is re-entrant: each
attempt clones into a fresh directory and the agent re-derives its patch, so a
replayed job is safe.

``running -> queued`` is a legal edge in the state machine, so the sweep uses
:func:`~app.workers.state.transition`. Jobs already terminal or awaiting a human
are left untouched.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Job, JobState
from app.telemetry.logging import get_logger
from app.workers.progress import record_log
from app.workers.state import transition

log = get_logger("workers.recovery")


async def recover_stuck_jobs(session: AsyncSession) -> list[str]:
    """Reset ``running`` jobs to ``queued`` and return their ids (as strings).

    Idempotent: a second call after the sweep finds nothing. The caller commits
    the session and re-enqueues each returned id.
    """
    stuck = (
        (await session.execute(select(Job).where(Job.state == JobState.RUNNING))).scalars().all()
    )
    recovered: list[str] = []
    for job in stuck:
        transition(job, JobState.QUEUED)
        await record_log(session, job.id, "recovered after worker restart; re-queued")
        recovered.append(str(job.id))
    if recovered:
        log.warning("recovered_stuck_jobs", count=len(recovered), job_ids=recovered)
    return recovered
