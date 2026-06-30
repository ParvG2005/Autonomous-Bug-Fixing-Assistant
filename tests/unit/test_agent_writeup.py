"""Tests for the reasoning writeup and the deterministic change summary."""

from __future__ import annotations

from app.agent.issue import parse_issue
from app.agent.localize import Suspect
from app.agent.models import AgentResult, FileEdit, StopReason, TokenUsage
from app.agent.writeup import build_writeup, change_summary

_BEFORE = "def divide(a, b):\n    return a / b\n"
_AFTER = "def divide(a, b):\n    if b == 0:\n        return 0\n    return a / b\n"


def _result(*, resolved: bool, edits: list[FileEdit], summary: str = "") -> AgentResult:
    from app.agent.edit import unified_diff

    return AgentResult(
        stop_reason=StopReason.RESOLVED if resolved else StopReason.COMPLETED,
        resolved=resolved,
        iterations=2,
        usage=TokenUsage(input_tokens=100, output_tokens=50),
        edits=edits,
        diff=unified_diff(edits),
        plan="1. read calc.py\n2. guard against zero",
        summary=summary,
    )


def test_change_summary_counts_insertions_and_deletions() -> None:
    edits = [FileEdit(path="calc.py", before=_BEFORE, after=_AFTER)]
    summary = change_summary(edits)
    assert summary.files_changed == ["calc.py"]
    assert summary.insertions == 2  # two added lines (the guard)
    assert summary.deletions == 0
    assert "calc.py" in str(summary)


def test_change_summary_empty() -> None:
    summary = change_summary([])
    assert summary.files_changed == []
    assert summary.insertions == 0
    assert summary.deletions == 0


def test_writeup_contains_sections_for_a_resolved_fix() -> None:
    task = parse_issue(
        "divide crashes\n\n`divide(1, 0)` raises.\nZeroDivisionError: division by zero"
    )
    suspects = [Suspect(path="calc.py", score=5.0, reasons=["traceback frame at line 5"])]
    result = _result(
        resolved=True,
        edits=[FileEdit(path="calc.py", before=_BEFORE, after=_AFTER)],
        summary="Guarded divide() against a zero denominator.",
    )

    md = build_writeup(task, suspects, result, flags=[])

    assert "# " in md  # has a heading
    assert "divide crashes" in md
    assert "calc.py" in md
    assert "ZeroDivisionError" in md
    assert "Guarded divide()" in md
    assert "RESOLVED" in md
    assert "```diff" in md  # the diff is embedded


def test_writeup_surfaces_guardrail_flags() -> None:
    task = parse_issue("bug")
    result = _result(resolved=False, edits=[])
    md = build_writeup(task, [], result, flags=["flagged: refusing to edit lockfile uv.lock"])
    assert "uv.lock" in md
    assert "UNRESOLVED" in md
