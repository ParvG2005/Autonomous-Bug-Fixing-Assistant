"""Reasoning writeup + change summary for a completed fix (Phase 4).

The deliverable is a human-readable explanation of *what the bug was, how it was
localized, what changed, and how we know it's fixed* — assembled deterministically
from the structured run so it costs no extra tokens and always matches the actual
result. :func:`change_summary` gives the headline files/insertions/deletions;
:func:`build_writeup` renders the full Markdown report a reviewer reads alongside
the diff.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.edit import unified_diff
from app.agent.issue import IssueTask
from app.agent.localize import Suspect
from app.agent.models import AgentResult, FileEdit


@dataclass(frozen=True)
class ChangeSummary:
    """Headline counts for an edit set."""

    files_changed: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0

    def __str__(self) -> str:
        files = ", ".join(self.files_changed) or "no files"
        return f"{files} (+{self.insertions}/-{self.deletions})"


def change_summary(edits: list[FileEdit]) -> ChangeSummary:
    """Compute files-changed and insertion/deletion counts from the net diff."""
    files: list[str] = []
    seen: set[str] = set()
    for edit in edits:
        if edit.path not in seen and edit.before != edit.after:
            seen.add(edit.path)
            files.append(edit.path)

    insertions = deletions = 0
    for line in unified_diff(edits).splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            insertions += 1
        elif line.startswith("-"):
            deletions += 1
    return ChangeSummary(files_changed=files, insertions=insertions, deletions=deletions)


def build_writeup(
    task: IssueTask,
    suspects: list[Suspect],
    result: AgentResult,
    *,
    flags: list[str],
) -> str:
    """Render the Markdown reasoning writeup for a finished run."""
    verdict = "RESOLVED" if result.resolved else "UNRESOLVED"
    summary = change_summary(result.edits)
    lines: list[str] = [f"# Fix writeup: {task.title or 'bug'}", "", f"**Verdict: {verdict}**", ""]

    lines += ["## Issue", "", task.body.strip() or "(no description)", ""]
    if task.error_message:
        lines += [f"Reported exception: `{task.error_message}`", ""]

    lines += ["## Localization", ""]
    if suspects:
        for suspect in suspects[:5]:
            why = "; ".join(suspect.reasons) or "ranked by lexical signal"
            lines.append(f"- `{suspect.path}` (score {suspect.score:g}) — {why}")
    else:
        lines.append("- No suspect files ranked from the issue; agent searched the repo.")
    lines.append("")

    lines += ["## Root cause & fix", ""]
    lines.append(result.summary.strip() or "(no summary provided by the agent)")
    lines.append("")

    lines += ["## Change summary", "", f"Files: {summary}", ""]
    if result.diff:
        lines += ["```diff", result.diff.rstrip("\n"), "```", ""]
    else:
        lines += ["_No source changes were made._", ""]

    lines += ["## Verification", ""]
    lines.append(
        f"Authoritative test run reports **{verdict}** "
        f"({result.iterations} turns, {result.usage.total} tokens)."
    )
    lines.append("")

    if flags:
        lines += ["## Guardrail flags", ""]
        lines += [f"- {flag}" for flag in flags]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
