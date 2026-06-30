"""Shared helpers for the simpler language adapters (Phase 8 extension).

The Python/Node/Go adapters each hand-roll a full result parser because their
output formats are rich and well-specified. The broader language set added here
(Rust, Ruby, Java, .NET, PHP, …) shares a common shape: drive the standard test
command, decide red/green from the exit code (and a counts line when the tool
prints one), and pull ``file:line`` frames out of the combined output. This base
captures exactly that so each new adapter stays small and consistent.

The agent loop needs three things from a run: did it pass, what failed, and
where (frames). This base delivers all three; per-test count fidelity is
best-effort (overridable via :meth:`BaseRegexAdapter._count`).
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from app.runner.models import Framework, Outcome, TestFailure, TestRunResult, TraceFrame
from app.sandbox.models import ExecResult

_SKIP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "target",
    "build",
    "dist",
    "bin",
    "obj",
    "__pycache__",
    ".venv",
    ".gradle",
    ".mvn",
}


def relativize(file: str, root: str | Path | None) -> str:
    """Make an absolute in-workspace path workspace-relative (POSIX semantics)."""
    if root is None:
        return file
    try:
        p = PurePosixPath(file)
        r = PurePosixPath(str(root))
        if p.is_absolute() and p.is_relative_to(r):
            return str(p.relative_to(r))
    except ValueError:
        return file
    return file


def parse_frames_with(
    pattern: re.Pattern[str], text: str, workspace: str | Path | None = None
) -> list[TraceFrame]:
    """Extract frames from ``text`` using ``pattern`` (needs ``file`` + ``line`` groups)."""
    frames: list[TraceFrame] = []
    for m in pattern.finditer(text):
        gd = m.groupdict()
        try:
            line = int(gd.get("line") or 0)
        except ValueError:
            continue
        frames.append(
            TraceFrame(
                file=relativize(gd.get("file") or "", workspace),
                line=line,
                function=(gd.get("func") or "").strip(),
            )
        )
    return frames


def has_file_with_suffix(workspace: Path, suffixes: tuple[str, ...]) -> bool:
    """True if any non-vendored file under ``workspace`` ends with one of ``suffixes``."""
    for path in workspace.rglob("*"):
        if path.is_file() and path.name.endswith(suffixes):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            return True
    return False


class BaseRegexAdapter:
    """A language adapter whose result is exit-code + regex driven.

    Subclasses set ``framework``/``image``/``commands`` and the ``frame_re``
    class attribute, and implement ``detect``/``install_command``/``build_command``.
    """

    framework: Framework
    image: str
    commands: frozenset[str]
    frame_re: re.Pattern[str]
    #: Marker that prefixes a single failing-test's headline message, if any.
    fail_marker: str | None = None

    def detect(self, workspace: Path) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def install_command(self, workspace: Path) -> list[str] | None:  # pragma: no cover
        return None

    def build_command(self, targets: list[str] | None = None) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def parse_frames(self, text: str, workspace: str | Path | None = None) -> list[TraceFrame]:
        return parse_frames_with(self.frame_re, text, workspace)

    def _count(self, combined: str) -> tuple[int, int, int]:
        """Return ``(passed, failed, skipped)`` best-effort. Default: unknown (zeros)."""
        return (0, 0, 0)

    def _failure_message(self, combined: str) -> str:
        """A short headline for the failure (first marker line, else first stderr line)."""
        if self.fail_marker:
            for line in combined.splitlines():
                if self.fail_marker in line:
                    return line.strip()[:300]
        for line in combined.splitlines():
            if line.strip():
                return line.strip()[:300]
        return "tests failed"

    def parse_result(
        self, exec_result: ExecResult, workspace: str | Path | None = None
    ) -> TestRunResult:
        combined = exec_result.stdout + "\n" + exec_result.stderr
        passed, failed, skipped = self._count(combined)

        if exec_result.timed_out:
            outcome = Outcome.TIMEOUT
        elif exec_result.returncode == 0:
            outcome = Outcome.PASSED
        else:
            outcome = Outcome.FAILED

        failures: list[TestFailure] = []
        if outcome is Outcome.FAILED:
            if not failed:
                failed = max(1, failed)
            failures.append(
                TestFailure(
                    nodeid=self.framework.value,
                    message=self._failure_message(combined),
                    frames=self.parse_frames(combined, workspace),
                )
            )

        return TestRunResult(
            framework=self.framework,
            outcome=outcome,
            passed=passed,
            failed=failed,
            errors=0,
            skipped=skipped,
            failures=failures,
            duration_s=exec_result.duration_s,
            returncode=exec_result.returncode,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
        )
