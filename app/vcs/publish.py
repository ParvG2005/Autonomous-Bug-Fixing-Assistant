"""The one and only remote-write path (Phase 5 / SECURITY.md C1 + C4).

:func:`open_draft_pr_for_fix` is the sole function in the system that mutates a
GitHub repo. Its contract, in order:

1. **Assert approval first.** It calls :func:`~app.vcs.approval.assert_approved`
   before anything else; with no ``approved`` record it raises and never mints a
   token or touches the network (C1).
2. **Mint a token inside this path**, use it, and discard it on exit — the token
   is held only for the duration of the call (C4).
3. **Open a draft PR** (never a ready PR, never a merge) and post the reasoning
   as a comment.

Both the approval store and the token minter are injected, so the whole path
runs offline against fakes in tests; only the live CLI wires real ones.
"""

from __future__ import annotations

from typing import Protocol

from app.vcs.approval import ApprovalStore, assert_approved
from app.vcs.auth import InstallationToken, TokenMinter
from app.vcs.github import GitHubClient
from app.vcs.models import DraftPR, FileChange, FixBundle, RepoRef


class _Client(Protocol):
    """The subset of :class:`~app.vcs.github.GitHubClient` publish depends on."""

    def commit_files(
        self, *, base_branch: str, head_branch: str, message: str, changes: list[FileChange]
    ) -> str: ...

    def open_draft_pr(self, *, title: str, head: str, base: str, body: str) -> DraftPR: ...

    def comment(self, *, number: int, body: str) -> None: ...

    def close(self) -> None: ...


class ClientFactory(Protocol):
    def __call__(self, repo: RepoRef, token: InstallationToken) -> _Client: ...


def open_draft_pr_for_fix(
    bundle: FixBundle,
    *,
    store: ApprovalStore,
    token_minter: TokenMinter,
    client_factory: ClientFactory = GitHubClient,
) -> DraftPR:
    """Open a human-approved draft PR for ``bundle``; return the created PR.

    Raises :class:`~app.vcs.approval.ApprovalError` if the job is not approved
    (checked before any token mint or network call).
    """
    # 1. C1: refuse outright unless an approved record exists.
    assert_approved(store, bundle.job_id)

    if bundle.is_empty:
        raise ValueError("fix bundle has no file changes; nothing to open a PR for")

    # 2. C4: token minted here, used, and discarded in `finally`.
    token = token_minter(bundle.repo.installation_id)
    client = client_factory(bundle.repo, token)
    try:
        client.commit_files(
            base_branch=bundle.base_branch,
            head_branch=bundle.head_branch,
            message=bundle.commit_message,
            changes=bundle.changes,
        )
        pr = client.open_draft_pr(
            title=bundle.title,
            head=bundle.head_branch,
            base=bundle.base_branch,
            body=bundle.body,
        )
        if bundle.reasoning_comment:
            client.comment(number=pr.number, body=bundle.reasoning_comment)
        return pr
    finally:
        client.close()
        del token  # drop the only reference; not persisted anywhere.
