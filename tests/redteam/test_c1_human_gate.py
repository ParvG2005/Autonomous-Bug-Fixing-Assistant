"""C1 — Human gate: no push / merge / non-draft PR without recorded approval.

SECURITY.md §3 C1 + §5 category 6 (remote-write coercion). Proves:
  (a) opening a PR with no APPROVAL row is refused *before* any token is minted;
  (b) an explicit ``rejected`` decision is refused;
  (c) every PR-create call carries ``draft=true`` (asserted against the real client);
  (d) static: no merge / push-to-base / ready-PR capability exists in ``app/vcs``.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from app.vcs.approval import Approval, ApprovalError, Decision, InMemoryApprovalStore
from app.vcs.auth import InstallationToken
from app.vcs.github import GitHubClient
from app.vcs.models import DraftPR, FileChange, FixBundle, RepoRef
from app.vcs.publish import open_draft_pr_for_fix

pytestmark = pytest.mark.redteam

_REPO = RepoRef(owner="acme", name="widget", installation_id=5)


def _bundle(job_id: str = "job-1") -> FixBundle:
    return FixBundle(
        job_id=job_id,
        repo=_REPO,
        base_branch="main",
        head_branch="fix/job-1",
        title="Fix",
        commit_message="fix it",
        body="why",
        changes=[FileChange(path="calc.py", content="x = 1\n")],
        reasoning_comment="reasoning",
    )


def test_no_approval_row_refused_before_token_mint() -> None:
    store = InMemoryApprovalStore()  # empty
    minted: list[int] = []

    def minter(install_id: int) -> InstallationToken:
        minted.append(install_id)
        return InstallationToken(value="t", expires_at="")

    with pytest.raises(ApprovalError):
        open_draft_pr_for_fix(_bundle(), store=store, token_minter=minter)
    assert minted == []  # never reached the network / never held a credential


def test_rejected_decision_refused() -> None:
    store = InMemoryApprovalStore()
    store.record(
        Approval(job_id="job-1", decision=Decision.REJECTED, actor="reviewer", decided_at="t")
    )
    with pytest.raises(ApprovalError):
        open_draft_pr_for_fix(
            _bundle(),
            store=store,
            token_minter=lambda i: InstallationToken(value="t", expires_at=""),
        )


def test_pr_creation_always_sets_draft_true() -> None:
    """Drive the real GitHubClient through a mock transport; capture the /pulls body."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/pulls"):
            import json

            captured.update(json.loads(request.content))
            return httpx.Response(201, json={"number": 7, "html_url": "https://example/pr/7"})
        raise AssertionError(f"unexpected call: {request.method} {request.url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = GitHubClient(_REPO, InstallationToken(value="t", expires_at=""), http=http)
    pr = client.open_draft_pr(title="t", head="fix/x", base="main", body="b")

    assert isinstance(pr, DraftPR)
    assert captured["draft"] is True  # C1: ready PRs are not creatable


def test_no_merge_or_force_push_capability_in_vcs(app_source_files: list[Path]) -> None:
    """Static proof: the remote-write module has no merge / ready-PR escape hatch."""
    vcs_sources = [p for p in app_source_files if "vcs" in p.parts]
    assert vcs_sources, "expected app/vcs sources to scan"

    # Forbidden API shapes anywhere in the remote-write plane.
    forbidden = [
        re.compile(r"/pulls/\{?\w*\}?/merge"),  # merge a PR
        re.compile(r"/merges\b"),  # repo merge endpoint
        re.compile(r'"draft"\s*:\s*False'),  # an explicit ready PR
        re.compile(r"draft\s*=\s*False"),
        re.compile(r"force\s*=\s*True"),
        re.compile(r"force-with-lease|--force\b"),
    ]
    for path in vcs_sources:
        text = path.read_text(encoding="utf-8")
        for pat in forbidden:
            assert not pat.search(text), f"{path.name}: forbidden pattern {pat.pattern}"


def test_open_draft_pr_is_the_only_pulls_post(app_source_files: list[Path]) -> None:
    """The only POST to /pulls in the codebase is the draft path in github.py."""
    hits = [
        p.name for p in app_source_files if re.search(r'"/pulls"', p.read_text(encoding="utf-8"))
    ]
    assert hits == ["github.py"], f"unexpected /pulls writers: {hits}"
