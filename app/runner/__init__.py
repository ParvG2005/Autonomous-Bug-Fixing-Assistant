"""Test-framework detection, test execution (inside sandbox), output +
stack-trace parsing (Phase 2+).

Reads untrusted workspace content. Produces structured ``{file, line, function}``
frames from stack traces.

Public surface: :func:`detect_framework`, :func:`run_pytest`, :func:`parse_frames`,
and the result value types.
"""

from __future__ import annotations

from app.runner.detect import detect_framework
from app.runner.models import (
    Framework,
    Outcome,
    TestFailure,
    TestRunResult,
    TraceFrame,
)
from app.runner.pytest_runner import NoTestFramework, parse_result, run_pytest
from app.runner.trace import parse_frames

__all__ = [
    "Framework",
    "NoTestFramework",
    "Outcome",
    "TestFailure",
    "TestRunResult",
    "TraceFrame",
    "detect_framework",
    "parse_frames",
    "parse_result",
    "run_pytest",
]
