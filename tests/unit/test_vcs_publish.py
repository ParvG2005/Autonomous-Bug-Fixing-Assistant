"""The single remote-write path: gate first, mint-use-discard, draft only."""

from __future__ import annotations

import pytest

from app.vcs.approval import (
    Approval,
    ApprovalError,
    Decision,
    InMemoryApprovalStore,
)
from app.vcs.auth import InstallationToken
from app.vcs.models import DraftPR, FileChange, FixBundle, RepoRef
from app.vcs.publish import open_draft_pr_for_fix

_REPO = RepoRef(owner="acme", name="widget", installation_id=5)


def _bundle(job_id: str = "job-1", *, changes: bool = True) -> FixBundle:
    return FixBundle(
        job_id=job_id,
        repo=_REPO,
        base_branch="main",
        head_branch="fix/job-1",
        title="Fix",
        commit_message="fix it",
        body="why",
        changes=[FileChange(path="calc.py", content="x=1\n")] if changes else [],
        reasoning_comment="here is my reasoning",
    )


def _approve(store: InMemoryApprovalStore, job_id: str = "job-1") -> None:
    store.record(
        Approval(
            job_id=job_id, decision=Decision.APPROVED, actor="a", decided_at="2026-06-30T0:0:0"
        )
    )


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.closed = False

    def commit_files(self, **kw: object) -> str:
        self.calls.append("commit")
        return "sha"

    def open_draft_pr(self, **kw: object) -> DraftPR:
        self.calls.append("pr")
        return DraftPR(number=3, url="u", head_branch="fix/job-1")

    def comment(self, **kw: object) -> None:
        self.calls.append("comment")

    def close(self) -> None:
        self.closed = True


def test_refuses_without_approval_and_never_mints_token() -> None:
    store = InMemoryApprovalStore()  # empty
    minted: list[int] = []

    def minter(install_id: int) -> InstallationToken:
        minted.append(install_id)
        return InstallationToken(value="t", expires_at="")

    with pytest.raises(ApprovalError):
        open_draft_pr_for_fix(_bundle(), store=store, token_minter=minter)
    assert minted == []  # C1: aborted before any token / network


def test_approved_path_commits_opens_draft_and_comments() -> None:
    store = InMemoryApprovalStore()
    _approve(store)
    fake = _FakeClient()

    pr = open_draft_pr_for_fix(
        _bundle(),
        store=store,
        token_minter=lambda i: InstallationToken(value="t", expires_at=""),
        client_factory=lambda repo, token: fake,
    )
    assert pr.number == 3
    assert fake.calls == ["commit", "pr", "comment"]
    assert fake.closed is True  # C4: client/token released


def test_rejected_after_approval_is_refused() -> None:
    store = InMemoryApprovalStore()
    _approve(store)
    store.record(
        Approval(job_id="job-1", decision=Decision.REJECTED, actor="a", decided_at="2026-06-30")
    )
    with pytest.raises(ApprovalError):
        open_draft_pr_for_fix(
            _bundle(),
            store=store,
            token_minter=lambda i: InstallationToken(value="t", expires_at=""),
        )


def test_empty_bundle_refused_even_when_approved() -> None:
    store = InMemoryApprovalStore()
    _approve(store)
    with pytest.raises(ValueError, match="no file changes"):
        open_draft_pr_for_fix(
            _bundle(changes=False),
            store=store,
            token_minter=lambda i: InstallationToken(value="t", expires_at=""),
        )
