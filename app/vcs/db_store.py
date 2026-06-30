"""Adapt the DB approval record to the publish path's ``ApprovalStore`` protocol.

The DB is the source of truth for UI approvals (``app.db.approvals``). The publish
call (`open_draft_pr_for_fix`) is synchronous, so we pre-load the latest decision
and hand it a populated in-memory store rather than awaiting inside the gate.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.approvals import latest_decision
from app.models.entities import ApprovalDecision
from app.vcs.approval import Approval, Decision, InMemoryApprovalStore

_MAP = {
    ApprovalDecision.APPROVED: Decision.APPROVED,
    ApprovalDecision.REJECTED: Decision.REJECTED,
}


class DbApprovalStore(InMemoryApprovalStore):
    """An in-memory store pre-seeded from the DB. Read-only in practice."""


async def load_db_approval_store(session: AsyncSession, job_id: str) -> DbApprovalStore:
    """Pre-load ``job_id``'s latest DB decision into a fresh in-memory store.

    Returns an empty store if no decision exists yet, so ``assert_approved``
    correctly raises ``ApprovalError``.
    """
    store = DbApprovalStore()
    row = await latest_decision(session, uuid.UUID(job_id))
    if row is not None:
        store.record(
            Approval(
                job_id=job_id,
                decision=_MAP[row.decision],
                actor=row.actor,
                decided_at=row.decided_at.isoformat(),
                note=row.note or "",
            )
        )
    return store
