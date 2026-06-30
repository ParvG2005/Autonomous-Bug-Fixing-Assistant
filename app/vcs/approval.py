"""The human gate, persisted (Phase 5 / SECURITY.md C1).

No remote write happens unless an ``approved`` :class:`Approval` exists for the
job. Records are **append-only and immutable** — a reversal is a new record, and
the *latest* decision wins. :func:`assert_approved` is the single chokepoint the
remote-write path calls before touching GitHub.

Postgres-backed storage lands in Phase 6; until then a :class:`JsonFileApprovalStore`
persists decisions across CLI invocations and an :class:`InMemoryApprovalStore`
serves tests. Both satisfy the :class:`ApprovalStore` protocol so the publish path
is storage-agnostic.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


class Decision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalError(Exception):
    """Raised when a remote write is attempted without an ``approved`` record."""


@dataclass(frozen=True)
class Approval:
    """One immutable human decision for a job.

    ``decided_at`` is an ISO-8601 string supplied by the caller (no implicit
    clock, so records are reproducible and the value comes from the request).
    """

    job_id: str
    decision: Decision
    actor: str
    decided_at: str
    actor_source: str = "cli"
    note: str = ""


@runtime_checkable
class ApprovalStore(Protocol):
    """Append-only store of human decisions, keyed by job."""

    def record(self, approval: Approval) -> None: ...

    def latest(self, job_id: str) -> Approval | None: ...

    def is_approved(self, job_id: str) -> bool: ...


def _latest(records: list[Approval], job_id: str) -> Approval | None:
    for approval in reversed(records):
        if approval.job_id == job_id:
            return approval
    return None


class InMemoryApprovalStore:
    """Non-persistent store for tests and single-process use."""

    def __init__(self) -> None:
        self._records: list[Approval] = []

    def record(self, approval: Approval) -> None:
        self._records.append(approval)

    def latest(self, job_id: str) -> Approval | None:
        return _latest(self._records, job_id)

    def is_approved(self, job_id: str) -> bool:
        latest = self.latest(job_id)
        return latest is not None and latest.decision is Decision.APPROVED


class JsonFileApprovalStore:
    """JSON-lines store that survives across CLI runs.

    Append-only on disk: every :meth:`record` adds one line; the file is never
    rewritten, preserving the audit trail.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> list[Approval]:
        if not self.path.exists():
            return []
        records: list[Approval] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            raw["decision"] = Decision(raw["decision"])
            records.append(Approval(**raw))
        return records

    def record(self, approval: Approval) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = asdict(approval)
        row["decision"] = approval.decision.value
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    def latest(self, job_id: str) -> Approval | None:
        return _latest(self._load(), job_id)

    def is_approved(self, job_id: str) -> bool:
        latest = self.latest(job_id)
        return latest is not None and latest.decision is Decision.APPROVED


def assert_approved(store: ApprovalStore, job_id: str) -> Approval:
    """Return the approving record for ``job_id`` or raise :class:`ApprovalError`.

    This is the C1 chokepoint: the remote-write path calls it *first* and aborts
    on any non-approved state (missing record, or a later rejection).
    """
    latest = store.latest(job_id)
    if latest is None:
        raise ApprovalError(f"no approval record for job {job_id!r}; remote write refused")
    if latest.decision is not Decision.APPROVED:
        raise ApprovalError(
            f"job {job_id!r} latest decision is {latest.decision.value!r}; remote write refused"
        )
    return latest
