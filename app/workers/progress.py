"""Coarse-grained job progress, persisted as ``LOG`` artifacts (Phase 7).

The worker appends one short, human-readable line per pipeline milestone. They
are stored as :class:`~app.models.entities.Artifact` rows (``kind=log``) so the
status/SSE endpoints can replay them from the database alone — no Redis required
to *read* progress (Redis only carries the job hand-off). Lines are coarse
(phase boundaries, not per-token) so the per-row ``sha256`` cost is negligible.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Artifact, ArtifactKind, ArtifactStorage
from app.telemetry.logging import get_logger

log = get_logger("workers.progress")


async def record_log(
    session: AsyncSession,
    job_id: object,
    message: str,
    *,
    run_id: object | None = None,
) -> Artifact:
    """Append one progress line for ``job_id`` and flush it.

    Returns the created artifact. The caller owns the surrounding transaction.
    """
    body = message.encode("utf-8")
    artifact = Artifact(
        job_id=job_id,
        run_id=run_id,
        kind=ArtifactKind.LOG,
        storage=ArtifactStorage.INLINE_SMALL,
        content=message,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
    )
    session.add(artifact)
    await session.flush()
    log.info("job_progress", job_id=str(job_id), message=message)
    return artifact


async def read_logs(session: AsyncSession, job_id: object, *, after: int = 0) -> list[Artifact]:
    """Return this job's ``LOG`` artifacts in creation order, skipping the first ``after``."""
    rows = (
        (
            await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job_id, Artifact.kind == ArtifactKind.LOG)
                .order_by(Artifact.created_at, Artifact.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows[after:])
