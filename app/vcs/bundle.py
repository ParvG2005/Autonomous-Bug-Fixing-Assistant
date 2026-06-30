"""Bridge Phase 4 output to a Phase 5 :class:`~app.vcs.models.FixBundle`.

A verified :class:`~app.agent.solve.SolveResult` carries the edits, the change
summary, and the Markdown writeup. :func:`build_fix_bundle` packages those into
the credential-free bundle the remote-write path consumes — final file contents,
a commit message, a PR body, and the writeup as the reasoning comment.
"""

from __future__ import annotations

from app.agent.solve import SolveResult
from app.vcs.models import FixBundle, RepoRef, changes_from_edits, diff_of


def build_fix_bundle(
    *,
    job_id: str,
    repo: RepoRef,
    base_branch: str,
    result: SolveResult,
    head_branch: str | None = None,
) -> FixBundle:
    """Assemble the draft-PR bundle for a solved issue.

    The PR title is the issue title; the body carries the change summary and the
    unified diff; the full reasoning writeup is posted as a comment.
    """
    changes = changes_from_edits(result.agent.edits)
    title = result.task.title or "Automated fix"
    head = head_branch or f"bugfix/{job_id}"

    diff = diff_of(result.agent.edits)
    body = (
        f"Automated fix for: **{title}**\n\n"
        f"**Changes:** {result.summary}\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n\n"
        "_Opened as a draft for human review. See the reasoning in the comment below._"
    )
    return FixBundle(
        job_id=job_id,
        repo=repo,
        base_branch=base_branch,
        head_branch=head,
        title=f"Fix: {title}",
        commit_message=f"Fix: {title}\n\nAutomated bug fix for job {job_id}.",
        body=body,
        changes=changes,
        reasoning_comment=result.writeup,
    )
