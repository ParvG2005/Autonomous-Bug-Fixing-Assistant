"""The arq worker (Phase 7) — drains the queue, one isolated run per job.

``run_job`` is the single registered task: it loads its dependencies from the
worker context and hands off to :func:`~app.workers.pipeline.run_pipeline`.

On startup the worker performs **crash recovery** — any job left ``running`` by
a previous (dead) worker is reset to ``queued`` and re-enqueued. This is what
makes jobs recoverable across a worker crash (Phase 7 acceptance).

Run it with the console script ``bugfix-worker`` or ``arq app.workers.worker.WorkerSettings``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from app.agent.client import make_create_message
from app.core.settings import Settings, get_settings
from app.db.session import Database
from app.telemetry.logging import configure_logging, get_logger
from app.workers.pipeline import run_pipeline
from app.workers.queue import JobQueue, create_job_queue, redis_settings
from app.workers.recovery import recover_stuck_jobs

log = get_logger("workers.worker")


async def run_job(ctx: dict[str, Any], job_id: str) -> str:
    """arq task: run one job's pipeline. Returns the final job state value."""
    db: Database = ctx["db"]
    settings: Settings = ctx["settings"]
    create_message = ctx["create_message"]
    state = await run_pipeline(db, job_id, create_message=create_message, settings=settings)
    return state.value


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["settings"] = settings
    ctx["db"] = Database.from_settings(settings)
    ctx["create_message"] = make_create_message(settings)
    queue = await create_job_queue(settings)
    ctx["queue"] = queue

    # Crash recovery: reclaim jobs a dead worker left mid-run, then re-enqueue.
    db: Database = ctx["db"]
    async with db.session() as session:
        recovered = await recover_stuck_jobs(session)
    if recovered and queue is not None:
        for jid in recovered:
            await queue.enqueue(jid)


async def shutdown(ctx: dict[str, Any]) -> None:
    queue: JobQueue | None = ctx.get("queue")
    if queue is not None:
        await queue.close()
    db: Database | None = ctx.get("db")
    if db is not None:
        await db.dispose()


def _worker_redis_settings() -> object:
    settings = get_settings()
    return redis_settings(settings.redis_url or "redis://localhost:6379")


class WorkerSettings:
    """arq worker configuration (discovered by ``arq <module>.WorkerSettings``)."""

    functions: ClassVar[list[Callable[..., Any]]] = [run_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _worker_redis_settings()
    max_jobs = 4  # one container per job; bound concurrent runs per worker
    job_timeout = 1800  # 30 min hard ceiling per job


def main() -> None:
    """Console-script entry point (``bugfix-worker``)."""
    from arq import run_worker

    run_worker(WorkerSettings)  # type: ignore[arg-type]
