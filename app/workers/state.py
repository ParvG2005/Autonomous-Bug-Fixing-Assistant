"""Job state machine (Phase 7).

The single source of truth for legal JOB transitions (DATA_MODEL.md §3). Every
state change goes through :func:`transition`, which refuses an illegal move
rather than silently corrupting the lifecycle:

    queued ──▶ running ──▶ awaiting_approval ──▶ approved ──▶ done
                  │                  │                          ▲
                  └──────────────────┴──────────▶ failed ───────┘
                                     └──────────▶ rejected

``approved``/``rejected`` are driven by the human gate (Phase 5 approval store);
the worker only ever drives ``queued → running → {awaiting_approval, failed}``.
A reject or a post-approval publish closes the job out (``rejected``/``done``).
"""

from __future__ import annotations

from app.models.entities import Job, JobState

#: Legal forward transitions. Keys are the current state; values the allowed next
#: states. Terminal states (``done``/``failed``/``rejected``) have no outgoing edge.
ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.FAILED}),
    JobState.RUNNING: frozenset({JobState.AWAITING_APPROVAL, JobState.FAILED, JobState.QUEUED}),
    JobState.AWAITING_APPROVAL: frozenset({JobState.APPROVED, JobState.REJECTED, JobState.FAILED}),
    JobState.APPROVED: frozenset({JobState.DONE, JobState.FAILED}),
    JobState.REJECTED: frozenset(),
    JobState.DONE: frozenset(),
    JobState.FAILED: frozenset(),
}

#: Live (non-terminal) states — a job here still owns work or a pending decision.
LIVE_STATES: frozenset[JobState] = frozenset(
    {
        JobState.QUEUED,
        JobState.RUNNING,
        JobState.AWAITING_APPROVAL,
        JobState.APPROVED,
    }
)

#: Terminal states — no further transition is legal.
TERMINAL_STATES: frozenset[JobState] = frozenset(
    {JobState.DONE, JobState.FAILED, JobState.REJECTED}
)


class InvalidTransition(RuntimeError):
    """Raised when a job is moved between states the machine forbids."""

    def __init__(self, frm: JobState, to: JobState) -> None:
        super().__init__(f"illegal job transition {frm.value!r} -> {to.value!r}")
        self.frm = frm
        self.to = to


def can_transition(frm: JobState, to: JobState) -> bool:
    """True if ``frm -> to`` is a legal edge in the state machine."""
    return to in ALLOWED_TRANSITIONS.get(frm, frozenset())


def transition(job: Job, to: JobState, *, reason: str | None = None) -> Job:
    """Move ``job`` to ``to`` in place, enforcing the state machine.

    On a move to :attr:`JobState.FAILED` the ``reason`` is recorded on the job;
    transitioning *out* of a non-failed state clears any stale failure reason.
    Caller owns the session/commit — this only mutates the ORM object.
    """
    if not can_transition(job.state, to):
        raise InvalidTransition(job.state, to)
    job.state = to
    if to is JobState.FAILED:
        job.failure_reason = reason
    elif reason is None:
        job.failure_reason = None
    return job
