"""Redis-backed job queue (Phase 7).

A thin wrapper over an arq Redis pool. The API enqueues a job id; the worker
consumes it. Enqueues are **deduplicated by job id** (``_job_id="job:<uuid>"``),
so a duplicate webhook delivery — or a re-enqueue racing an in-flight run —
collapses to one task rather than running the pipeline twice.

The pool is optional at the edges: when ``redis_url`` is unset (unit tests, the
offline webhook suite) :func:`create_job_queue` returns ``None`` and callers
skip enqueuing. The fire-and-forget contract still holds — the row is persisted;
a worker drains it once Redis is configured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.settings import Settings
from app.telemetry.logging import get_logger

if TYPE_CHECKING:
    from arq.connections import RedisSettings

#: The arq task name the worker registers (see :mod:`app.workers.worker`).
RUN_JOB_TASK = "run_job"

log = get_logger("workers.queue")


def job_dedup_key(job_id: object) -> str:
    """The arq ``_job_id`` for a pipeline job — one in-flight task per job id."""
    return f"job:{job_id}"


class JobQueue:
    """Owns an arq Redis pool and enqueues pipeline jobs."""

    def __init__(self, pool: object) -> None:
        self._pool = pool

    @property
    def pool(self) -> object:
        return self._pool

    async def enqueue(self, job_id: object) -> bool:
        """Enqueue ``run_job(job_id)``. Returns False if a task is already queued.

        arq returns ``None`` from ``enqueue_job`` when a job with the same
        ``_job_id`` is still queued/running — that is the dedup signal.
        """
        job = await self._pool.enqueue_job(  # type: ignore[attr-defined]
            RUN_JOB_TASK, str(job_id), _job_id=job_dedup_key(job_id)
        )
        enqueued = job is not None
        log.info("enqueue_job", job_id=str(job_id), enqueued=enqueued)
        return enqueued

    async def close(self) -> None:
        close = getattr(self._pool, "aclose", None) or getattr(self._pool, "close", None)
        if close is not None:
            await close()


def redis_settings(url: str) -> RedisSettings:
    """Build arq ``RedisSettings`` from a DSN."""
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(url)


async def create_job_queue(settings: Settings) -> JobQueue | None:
    """Open a :class:`JobQueue`, or ``None`` when no ``redis_url`` is configured."""
    if not settings.redis_url:
        log.info("queue_disabled", reason="redis_url not configured")
        return None
    from arq import create_pool

    pool = await create_pool(redis_settings(settings.redis_url))
    return JobQueue(pool)
