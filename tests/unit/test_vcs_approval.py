"""C1 human-gate semantics: append-only store + assert_approved chokepoint."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.vcs.approval import (
    Approval,
    ApprovalError,
    Decision,
    InMemoryApprovalStore,
    JsonFileApprovalStore,
    assert_approved,
)


def _ap(job_id: str, decision: Decision, *, actor: str = "alice") -> Approval:
    return Approval(
        job_id=job_id, decision=decision, actor=actor, decided_at="2026-06-30T00:00:00Z"
    )


def test_assert_approved_refuses_when_no_record() -> None:
    store = InMemoryApprovalStore()
    with pytest.raises(ApprovalError, match="no approval record"):
        assert_approved(store, "job-1")


def test_assert_approved_refuses_rejected() -> None:
    store = InMemoryApprovalStore()
    store.record(_ap("job-1", Decision.REJECTED))
    with pytest.raises(ApprovalError, match="rejected"):
        assert_approved(store, "job-1")


def test_assert_approved_returns_approving_record() -> None:
    store = InMemoryApprovalStore()
    store.record(_ap("job-1", Decision.APPROVED))
    approval = assert_approved(store, "job-1")
    assert approval.decision is Decision.APPROVED


def test_latest_decision_wins_and_is_append_only() -> None:
    """A reversal is a new row; the latest decision governs the gate."""
    store = InMemoryApprovalStore()
    store.record(_ap("job-1", Decision.APPROVED))
    store.record(_ap("job-1", Decision.REJECTED))  # reversal
    assert store.is_approved("job-1") is False
    with pytest.raises(ApprovalError):
        assert_approved(store, "job-1")
    # re-approval flips it back
    store.record(_ap("job-1", Decision.APPROVED))
    assert store.is_approved("job-1") is True


def test_json_file_store_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "approvals.jsonl"
    JsonFileApprovalStore(path).record(_ap("job-9", Decision.APPROVED, actor="bob"))

    reopened = JsonFileApprovalStore(path)
    latest = reopened.latest("job-9")
    assert latest is not None
    assert latest.decision is Decision.APPROVED
    assert latest.actor == "bob"
    assert reopened.is_approved("job-9") is True


def test_json_file_store_is_append_only_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "approvals.jsonl"
    store = JsonFileApprovalStore(path)
    store.record(_ap("j", Decision.APPROVED))
    store.record(_ap("j", Decision.REJECTED))
    assert len(path.read_text().splitlines()) == 2  # nothing rewritten
