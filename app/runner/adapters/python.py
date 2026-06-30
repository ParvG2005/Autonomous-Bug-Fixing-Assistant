"""Python / pytest adapter.

Wraps the original Phase 2 implementation (``detect``, ``parse``, ``trace``,
``pytest_runner``) behind the :class:`~app.runner.adapters.base.LanguageAdapter`
contract so the generic runner can drive it alongside the JS and Go adapters.
No parsing logic is duplicated here — this is a thin facade over the existing
modules.
"""

from __future__ import annotations

from pathlib import Path

from app.runner.detect import _has_pytest_config, _has_test_files
from app.runner.models import Framework, TestRunResult, TraceFrame
from app.runner.parse import build_failures, decide_outcome, parse_counts
from app.runner.trace import parse_frames
from app.sandbox.models import ExecResult

# Default image carries python + pytest (docker/sandbox.python.Dockerfile).
PYTHON_IMAGE = "bugfix-sandbox-python:latest"

_PYTEST_CMD = [
    "python",
    "-m",
    "pytest",
    "-q",
    "--tb=native",
    "-rfE",
    "-p",
    "no:cacheprovider",
]


class PytestAdapter:
    """Drives pytest; see :mod:`app.runner.pytest_runner` for the rationale."""

    framework = Framework.PYTEST
    image = PYTHON_IMAGE
    commands = frozenset({"python", "pytest", "pip"})

    def detect(self, workspace: Path) -> bool:
        return _has_pytest_config(workspace) or _has_test_files(workspace)

    def install_command(self, workspace: Path) -> list[str] | None:
        if (workspace / "requirements.txt").is_file():
            return ["pip", "install", "-r", "requirements.txt"]
        # An installable package (pyproject/setup) — editable install pulls deps.
        if (workspace / "pyproject.toml").is_file() or (workspace / "setup.py").is_file():
            return ["pip", "install", "-e", "."]
        return None

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        cmd = list(_PYTEST_CMD)
        if targets:
            cmd += list(targets)
        return cmd

    def parse_frames(self, text: str, workspace: str | Path | None = None) -> list[TraceFrame]:
        return parse_frames(text, workspace)

    def parse_result(
        self, exec_result: ExecResult, workspace: str | Path | None = None
    ) -> TestRunResult:
        from app.runner.models import Outcome, TestFailure

        combined = exec_result.stdout + "\n" + exec_result.stderr
        counts = parse_counts(combined)
        failures: list[TestFailure] = []
        if exec_result.timed_out:
            outcome = Outcome.TIMEOUT
        else:
            outcome = decide_outcome(counts, exec_result.returncode)
            if outcome in (Outcome.FAILED, Outcome.ERROR):
                failures = build_failures(combined, workspace)
        return TestRunResult(
            framework=self.framework,
            outcome=outcome,
            passed=counts.get("passed", 0),
            failed=counts.get("failed", 0),
            errors=counts.get("errors", 0),
            skipped=counts.get("skipped", 0),
            failures=failures,
            duration_s=exec_result.duration_s,
            returncode=exec_result.returncode,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
        )
