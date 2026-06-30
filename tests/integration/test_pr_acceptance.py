"""Phase 5 acceptance: a labeled issue → a real **draft** PR, only after approval.

⚠️ STOP-AND-ASK: this opens a real PR. It is skipped unless a disposable test
repo and GitHub App credentials are supplied via environment, and never runs in
CI by default. Set:

    BUGFIX_IT_OWNER, BUGFIX_IT_REPO, BUGFIX_IT_INSTALL_ID, BUGFIX_IT_BASE
    GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY        (the App credentials)

The test records an approval, opens the draft PR through the *only* remote-write
path, and asserts the returned PR exists. It also asserts the no-approval case is
refused before any token is minted.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from app.core.settings import get_settings
from app.vcs.approval import (
    Approval,
    ApprovalError,
    Decision,
    InMemoryApprovalStore,
)
from app.vcs.auth import settings_token_minter
from app.vcs.models import FileChange, FixBundle, RepoRef
from app.vcs.publish import open_draft_pr_for_fix

pytestmark = pytest.mark.integration

_REQUIRED = ("BUGFIX_IT_OWNER", "BUGFIX_IT_REPO", "BUGFIX_IT_INSTALL_ID")


def _repo() -> RepoRef:
    missing = [k for k in _REQUIRED if not os.getenv(k)]
    if missing:
        pytest.skip(f"set {', '.join(_REQUIRED)} to run the real-PR acceptance test")
    return RepoRef(
        owner=os.environ["BUGFIX_IT_OWNER"],
        name=os.environ["BUGFIX_IT_REPO"],
        installation_id=int(os.environ["BUGFIX_IT_INSTALL_ID"]),
    )


def _bundle(repo: RepoRef, job_id: str) -> FixBundle:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return FixBundle(
        job_id=job_id,
        repo=repo,
        base_branch=os.getenv("BUGFIX_IT_BASE", "main"),
        head_branch=f"bugfix/{job_id}-{stamp}",
        title="Fix: acceptance smoke",
        commit_message="Fix: acceptance smoke",
        body="Automated draft PR — Phase 5 acceptance.",
        changes=[FileChange(path=f".bugfix-acceptance-{stamp}.txt", content="ok\n")],
        reasoning_comment="Reasoning writeup goes here.",
    )


def test_no_approval_is_refused_before_token_mint() -> None:
    repo = _repo()
    settings = get_settings()
    minter = settings_token_minter(settings, now=int(datetime.now(UTC).timestamp()))
    with pytest.raises(ApprovalError):
        open_draft_pr_for_fix(
            _bundle(repo, "no-approval"),
            store=InMemoryApprovalStore(),
            token_minter=minter,
        )


def test_approved_issue_opens_real_draft_pr() -> None:
    repo = _repo()
    settings = get_settings()
    job_id = "acceptance"
    store = InMemoryApprovalStore()
    store.record(
        Approval(
            job_id=job_id,
            decision=Decision.APPROVED,
            actor="acceptance-test",
            decided_at=datetime.now(UTC).isoformat(),
        )
    )
    minter = settings_token_minter(settings, now=int(datetime.now(UTC).timestamp()))
    pr = open_draft_pr_for_fix(_bundle(repo, job_id), store=store, token_minter=minter)
    assert pr.number > 0
    assert pr.url.startswith("https://github.com/")
