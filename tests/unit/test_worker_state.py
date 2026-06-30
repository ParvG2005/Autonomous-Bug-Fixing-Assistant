"""The job state machine (Phase 7): legal edges enforced, terminals closed."""

from __future__ import annotations

import pytest

from app.models.entities import Job, JobState
from app.workers.state import (
    InvalidTransition,
    can_transition,
    transition,
)


def _job(state: JobState) -> Job:
    return Job(state=state)


def test_happy_path_edges_are_legal() -> None:
    assert can_transition(JobState.QUEUED, JobState.RUNNING)
    assert can_transition(JobState.RUNNING, JobState.AWAITING_APPROVAL)
    assert can_transition(JobState.AWAITING_APPROVAL, JobState.APPROVED)
    assert can_transition(JobState.APPROVED, JobState.DONE)


def test_recovery_edge_running_back_to_queued_is_legal() -> None:
    assert can_transition(JobState.RUNNING, JobState.QUEUED)


def test_terminal_states_have_no_outgoing_edge() -> None:
    for terminal in (JobState.DONE, JobState.FAILED, JobState.REJECTED):
        assert not can_transition(terminal, JobState.RUNNING)
        assert not can_transition(terminal, JobState.QUEUED)


def test_illegal_skip_raises() -> None:
    job = _job(JobState.QUEUED)
    with pytest.raises(InvalidTransition):
        transition(job, JobState.AWAITING_APPROVAL)
    assert job.state is JobState.QUEUED  # unchanged on refusal


def test_transition_records_then_clears_failure_reason() -> None:
    job = _job(JobState.RUNNING)
    transition(job, JobState.FAILED, reason="boom")
    assert job.state is JobState.FAILED
    assert job.failure_reason == "boom"

    job2 = _job(JobState.QUEUED)
    job2.failure_reason = "stale"
    transition(job2, JobState.RUNNING)
    assert job2.failure_reason is None  # cleared on a non-failure move
