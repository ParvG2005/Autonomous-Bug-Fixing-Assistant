"""Tests for parsing free-form issue text / stack traces into a structured task."""

from __future__ import annotations

from app.agent.issue import parse_issue

_ISSUE_WITH_TRACEBACK = """\
divide() crashes on zero denominator

When I call `divide(1, 0)` the program blows up instead of returning 0.

Traceback (most recent call last):
  File "calc.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero

Repro: pytest test_calc.py::test_divide_by_zero
"""


def test_parses_title_and_body() -> None:
    task = parse_issue(_ISSUE_WITH_TRACEBACK)
    assert task.title == "divide() crashes on zero denominator"
    assert "blows up" in task.body


def test_extracts_exception_type_and_message() -> None:
    task = parse_issue(_ISSUE_WITH_TRACEBACK)
    assert task.error_type == "ZeroDivisionError"
    assert task.error_message == "ZeroDivisionError: division by zero"
    assert task.has_traceback is True


def test_extracts_traceback_frames() -> None:
    task = parse_issue(_ISSUE_WITH_TRACEBACK)
    assert len(task.frames) == 1
    frame = task.frames[0]
    assert frame.file == "calc.py"
    assert frame.line == 5
    assert frame.function == "divide"


def test_extracts_referenced_paths_and_nodeids() -> None:
    task = parse_issue(_ISSUE_WITH_TRACEBACK)
    assert "calc.py" in task.referenced_paths
    # The node id is captured as a test target, not as a bare path.
    assert task.test_nodeids == ["test_calc.py::test_divide_by_zero"]
    assert "test_calc.py::test_divide_by_zero" not in task.referenced_paths


def test_extracts_identifiers_from_backticks_and_calls() -> None:
    task = parse_issue(_ISSUE_WITH_TRACEBACK)
    assert "divide" in task.identifiers


def test_plain_issue_without_traceback() -> None:
    task = parse_issue("Title only\n\nThe `Greeter.greet` method drops the prefix.")
    assert task.title == "Title only"
    assert task.has_traceback is False
    assert task.error_type == ""
    assert task.error_message == ""
    assert task.frames == []
    assert "Greeter.greet" in task.identifiers or "greet" in task.identifiers


def test_to_prompt_includes_key_signals() -> None:
    task = parse_issue(_ISSUE_WITH_TRACEBACK)
    prompt = task.to_prompt()
    assert "divide() crashes" in prompt
    assert "ZeroDivisionError" in prompt
    assert "calc.py:5" in prompt
