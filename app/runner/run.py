"""Generic, language-agnostic test runner (Phase 8).

:func:`run_tests` is the multi-language successor to :func:`run_pytest`: detect
the workspace's language adapter, build its test command, run it in the sandbox,
and parse the output into a :class:`~app.runner.models.TestRunResult`. The agent
loop and the worker pipeline call this so they never name a language.
"""

from __future__ import annotations

from pathlib import Path

from app.runner.adapters import detect_adapter
from app.runner.models import TestRunResult
from app.runner.pytest_runner import NoTestFramework
from app.sandbox.base import Sandbox
from app.sandbox.models import ResourceLimits

__all__ = ["NoTestFramework", "run_tests"]


def run_tests(
    workspace: Path,
    sandbox: Sandbox,
    *,
    targets: list[str] | None = None,
    limits: ResourceLimits | None = None,
    install: bool = False,
) -> TestRunResult:
    """Detect the language, run its tests in ``sandbox``, return structured results.

    When ``install`` is true and the adapter reports an install command, deps are
    installed first (needs sandbox egress, off by default — callers opt in).
    Raises :class:`NoTestFramework` if no adapter claims the workspace.
    """
    adapter = detect_adapter(workspace)
    if adapter is None:
        raise NoTestFramework(f"no supported test framework detected in {workspace}")

    limits = limits or ResourceLimits()
    if install:
        install_cmd = adapter.install_command(workspace)
        if install_cmd is not None:
            sandbox.run(install_cmd, workspace, limits)

    cmd = adapter.build_command(targets)
    exec_result = sandbox.run(cmd, workspace, limits)
    root = sandbox.mount_point(workspace)
    return adapter.parse_result(exec_result, root)
