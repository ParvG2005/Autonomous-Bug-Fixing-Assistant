"""Postgres-backed human decisions (Phase 12 / SECURITY.md C1).

Phase 5 persisted approvals to a JSON-lines file; Phase 6 added the ``approval``
table. This module is the async, DB-backed counterpart of
:mod:`app.vcs.approval`: it appends an immutable :class:`~app.models.entities.Approval`
row per decision (a reversal is a new row — never an update) and reads the latest
decision back. The dashboard's approve/reject endpoints are its only callers.

The caller owns the surrounding transaction/commit, matching
:func:`app.workers.progress.record_log`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Approval, ApprovalDecision


async def record_decision(
    session: AsyncSession,
    job_id: uuid.UUID,
    decision: ApprovalDecision,
    *,
    actor: str,
    actor_source: str = "dashboard",
    note: str | None = None,
) -> Approval:
    """Append one immutable decision row for ``job_id`` and flush it."""
    approval = Approval(
        job_id=job_id,
        decision=decision,
        actor=actor,
        actor_source=actor_source,
        note=note,
    )
    session.add(approval)
    await session.flush()
    return approval


async def latest_decision(session: AsyncSession, job_id: uuid.UUID) -> Approval | None:
    """Return the most recent decision for ``job_id``, or ``None`` if none exists."""
    return (
        await session.execute(
            select(Approval)
            .where(Approval.job_id == job_id)
            .order_by(Approval.decided_at.desc(), Approval.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
