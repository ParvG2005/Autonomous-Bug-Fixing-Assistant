"""Parsing a captured pytest run into a TestRunResult."""

from __future__ import annotations

from app.runner.models import Framework, Outcome
from app.runner.parse import build_failures, decide_outcome, parse_counts
from app.runner.pytest_runner import parse_result
from app.sandbox.models import ExecResult

# Representative `pytest -q --tb=native -rfE` output for the failing project.
_OUTPUT = """\
F.F                                                                      [100%]
=================================== FAILURES ===================================
_____________________________ test_divide_by_zero _____________________________
Traceback (most recent call last):
  File "/ws/test_calc.py", line 5, in test_divide_by_zero
    assert divide(1, 0) == 0
  File "/ws/calc.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero
________________________________ test_add_wrong ________________________________
Traceback (most recent call last):
  File "/ws/test_calc.py", line 13, in test_add_wrong
    assert add(2, 2) == 5
AssertionError: assert 4 == 5
=========================== short test summary info ============================
FAILED test_calc.py::test_divide_by_zero - ZeroDivisionError: division by zero
FAILED test_calc.py::test_add_wrong - AssertionError: assert 4 == 5
========================= 2 failed, 1 passed in 0.03s ==========================
"""


def test_parse_counts() -> None:
    counts = parse_counts(_OUTPUT)
    assert counts["failed"] == 2
    assert counts["passed"] == 1


def test_decide_outcome_failed() -> None:
    assert decide_outcome({"failed": 2, "passed": 1}, 1) is Outcome.FAILED


def test_decide_outcome_passed() -> None:
    assert decide_outcome({"passed": 3}, 0) is Outcome.PASSED


def test_decide_outcome_no_tests() -> None:
    assert decide_outcome({}, 5) is Outcome.NO_TESTS


def test_build_failures_has_correct_frames() -> None:
    failures = build_failures(_OUTPUT)
    by_id = {f.nodeid: f for f in failures}

    zero = by_id["test_calc.py::test_divide_by_zero"]
    assert "ZeroDivisionError" in zero.message
    assert [(f.file, f.line, f.function) for f in zero.frames] == [
        ("/ws/test_calc.py", 5, "test_divide_by_zero"),
        ("/ws/calc.py", 5, "divide"),
    ]
    assert zero.innermost_frame is not None
    assert zero.innermost_frame.function == "divide"

    wrong = by_id["test_calc.py::test_add_wrong"]
    assert wrong.frames[-1].function == "test_add_wrong"


def test_parse_result_end_to_end() -> None:
    exec_result = ExecResult(returncode=1, stdout=_OUTPUT, stderr="", duration_s=0.03)
    result = parse_result(exec_result, framework=Framework.PYTEST)
    assert result.outcome is Outcome.FAILED
    assert result.passed == 1
    assert result.failed == 2
    assert len(result.failures) == 2
    assert not result.ok


def test_parse_result_timeout() -> None:
    exec_result = ExecResult(returncode=-1, stdout="", stderr="", duration_s=120.0, timed_out=True)
    result = parse_result(exec_result)
    assert result.outcome is Outcome.TIMEOUT
