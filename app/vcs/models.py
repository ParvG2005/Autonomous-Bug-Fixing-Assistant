"""Value types for the remote-write plane (Phase 5).

These describe *what* would be pushed — a target repo, the file contents of a
fix, and the resulting draft PR — without holding any credential. The token
lives only inside :mod:`app.vcs.auth` / :mod:`app.vcs.publish`, never here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.edit import unified_diff
from app.agent.models import FileEdit


@dataclass(frozen=True)
class RepoRef:
    """A GitHub repository and the App installation that grants access to it."""

    owner: str
    name: str
    installation_id: int

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class FileChange:
    """The full final content of one file to commit (no partial hunks)."""

    path: str
    content: str


@dataclass(frozen=True)
class DraftPR:
    """The result of opening a draft pull request."""

    number: int
    url: str
    head_branch: str


@dataclass(frozen=True)
class FixBundle:
    """Everything the remote-write path needs to open one draft PR for a job.

    ``job_id`` ties the bundle to the APPROVAL row that gates it. ``changes`` is
    the final file content (derived from the agent's edits), ``body`` is the PR
    description, and ``reasoning_comment`` is posted as a follow-up comment.
    """

    job_id: str
    repo: RepoRef
    base_branch: str
    head_branch: str
    title: str
    commit_message: str
    body: str
    changes: list[FileChange] = field(default_factory=list)
    reasoning_comment: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.changes


def changes_from_edits(edits: list[FileEdit]) -> list[FileChange]:
    """Collapse an agent edit list to the final content of each touched file.

    Multiple edits to the same path coalesce to the last ``after``; files whose
    net content is unchanged are dropped (nothing to commit).
    """
    first_before: dict[str, str] = {}
    last_after: dict[str, str] = {}
    order: list[str] = []
    for edit in edits:
        if edit.path not in first_before:
            first_before[edit.path] = edit.before
            order.append(edit.path)
        last_after[edit.path] = edit.after

    return [
        FileChange(path=path, content=last_after[path])
        for path in order
        if first_before[path] != last_after[path]
    ]


def diff_of(edits: list[FileEdit]) -> str:
    """Unified diff of an edit set (re-exported for PR-body assembly)."""
    return unified_diff(edits)
