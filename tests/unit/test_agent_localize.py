"""Tests for ranking suspect files from an issue against the repo brain."""

from __future__ import annotations

from pathlib import Path

from app.agent.issue import parse_issue
from app.agent.localize import rank_suspects
from app.index.repo_brain import RepoBrain

_TRACEBACK_ISSUE = """\
divide crashes on zero

Traceback (most recent call last):
  File "calc.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero
"""


def test_traceback_file_ranks_first(failing_project: Path) -> None:
    brain = RepoBrain(failing_project)
    task = parse_issue(_TRACEBACK_ISSUE)

    suspects = rank_suspects(brain, task)

    assert suspects[0].path == "calc.py"
    assert suspects[0].score > 0
    assert any("traceback" in r.lower() for r in suspects[0].reasons)


def test_identifier_localizes_without_traceback(failing_project: Path) -> None:
    brain = RepoBrain(failing_project)
    task = parse_issue("The `divide` helper is wrong.")

    suspects = rank_suspects(brain, task)

    paths = [s.path for s in suspects]
    assert "calc.py" in paths


def test_nonexistent_referenced_path_is_dropped(failing_project: Path) -> None:
    brain = RepoBrain(failing_project)
    task = parse_issue("See nope.py for the bug.")

    suspects = rank_suspects(brain, task)

    assert all(s.path != "nope.py" for s in suspects)


def test_limit_caps_results(failing_project: Path) -> None:
    brain = RepoBrain(failing_project)
    task = parse_issue(_TRACEBACK_ISSUE)

    suspects = rank_suspects(brain, task, limit=1)

    assert len(suspects) <= 1
