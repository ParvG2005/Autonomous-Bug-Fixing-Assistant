"""build_fix_bundle packages a SolveResult into a credential-free FixBundle."""

from __future__ import annotations

from app.agent.issue import IssueTask
from app.agent.models import AgentResult, FileEdit, StopReason, TokenUsage
from app.agent.solve import SolveResult
from app.agent.writeup import ChangeSummary
from app.vcs.bundle import build_fix_bundle
from app.vcs.models import RepoRef


def _solve_result() -> SolveResult:
    task = IssueTask(title="divide by zero", body="divide(1,0) should be 0")
    agent = AgentResult(
        stop_reason=StopReason.RESOLVED,
        resolved=True,
        iterations=3,
        usage=TokenUsage(),
        edits=[FileEdit(path="calc.py", before="a/b\n", after="0 if b==0 else a/b\n")],
        diff="--- a/calc.py\n+++ b/calc.py\n",
    )
    return SolveResult(
        task=task,
        suspects=[],
        agent=agent,
        flags=[],
        writeup="## Reasoning\nfixed it",
        summary=ChangeSummary(files_changed=["calc.py"], insertions=1, deletions=1),
    )


def test_build_fix_bundle_packs_changes_title_and_writeup() -> None:
    repo = RepoRef(owner="acme", name="calc", installation_id=2)
    bundle = build_fix_bundle(job_id="job-1", repo=repo, base_branch="main", result=_solve_result())
    assert bundle.head_branch == "bugfix/job-1"
    assert bundle.title == "Fix: divide by zero"
    assert [c.path for c in bundle.changes] == ["calc.py"]
    assert bundle.changes[0].content == "0 if b==0 else a/b\n"
    assert "fixed it" in bundle.reasoning_comment
    assert not bundle.is_empty
