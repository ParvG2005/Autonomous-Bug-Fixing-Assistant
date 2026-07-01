"""Run pytest inside a sandbox and return a structured result.

Ties the pieces together: detect the framework, build a deterministic pytest
invocation, hand it to a :class:`~app.sandbox.base.Sandbox` to execute under
resource caps, then parse stdout into a :class:`TestRunResult`.

The invocation is ``python -m pytest -q --tb=native -rfE -p no:cacheprovider``:

* ``--tb=native`` makes every traceback a standard CPython one so the frame
  parser is simple and robust (:mod:`app.runner.trace`);
* ``-rfE`` prints a short summary of failures and errors (stable node ids);
* ``-p no:cacheprovider`` keeps the read-only workspace clean (no ``.pytest_cache``).
"""

from __future__ import annotations

import os
import posixpath
from pathlib import Path

from app.runner.detect import detect_framework
from app.runner.importable import ensure_importable
from app.runner.models import Framework, Outcome, TestFailure, TestRunResult
from app.runner.parse import build_failures, decide_outcome, parse_counts
from app.sandbox.base import Sandbox
from app.sandbox.models import ExecResult, ResourceLimits

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


class NoTestFramework(RuntimeError):
    """Raised when no supported test framework is detected in the workspace."""


def build_command(targets: list[str] | None = None) -> list[str]:
    """Return the pytest command, optionally restricted to ``targets``."""
    cmd = list(_PYTEST_CMD)
    if targets:
        cmd += list(targets)
    return cmd


def parse_result(
    exec_result: ExecResult,
    workspace: str | Path | None = None,
    framework: Framework = Framework.PYTEST,
) -> TestRunResult:
    """Turn a raw :class:`ExecResult` into a :class:`TestRunResult`.

    ``workspace`` is the relativization root — the workspace's mount point inside
    the sandbox (``/workspace`` for Docker, the host path for the local fallback).
    """
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
        framework=framework,
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


def run_pytest(
    workspace: Path,
    sandbox: Sandbox,
    *,
    targets: list[str] | None = None,
    limits: ResourceLimits | None = None,
) -> TestRunResult:
    """Detect pytest, run it in ``sandbox``, and return structured results.

    Raises :class:`NoTestFramework` if the workspace has no pytest setup.
    """
    framework = detect_framework(workspace)
    if framework is None:
        raise NoTestFramework(f"no supported test framework detected in {workspace}")

    cmd = build_command(targets)
    # Relativize frames against wherever the sandbox mounted the workspace.
    root = sandbox.mount_point(workspace)
    env = _import_env(workspace, root)
    exec_result = sandbox.run(cmd, workspace, limits or ResourceLimits(), env=env)
    return parse_result(exec_result, workspace=root, framework=framework)


def _import_env(workspace: Path, mount_root: str) -> dict[str, str]:
    """Make the repo importable and return the env (``PYTHONPATH``) for the run.

    :func:`ensure_importable` returns segments relative to the workspace; map each
    onto ``mount_root`` (the workspace path *inside* the sandbox) since that is
    where the run actually sees them.
    """
    segments = ensure_importable(workspace)
    entries = [mount_root if seg == "" else posixpath.join(mount_root, seg) for seg in segments]
    return {"PYTHONPATH": os.pathsep.join(entries)}
