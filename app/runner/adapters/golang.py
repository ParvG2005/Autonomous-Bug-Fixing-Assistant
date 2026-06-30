"""Go adapter — ``go test``.

Go's test framework is in the standard library, so the zero-dependency path is
natural: ``go test ./... -v``. Verbose output gives per-test result lines and
inline failure logs::

    === RUN   TestDivide
        calc_test.go:11: Divide(1, 0) = 0; want error
    --- FAIL: TestDivide (0.00s)
    === RUN   TestAdd
    --- PASS: TestAdd (0.00s)
    FAIL
    FAIL    example/calc    0.002s

Counts come from ``--- PASS/FAIL/SKIP:`` lines; failure messages + frames from
each test's ``file.go:line: message`` logs (and from panic stacks when a test
crashes). A compile error (``# pkg`` followed by ``file.go:5:1: ...``) surfaces
as an ERROR outcome.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from app.runner.models import Framework, Outcome, TestFailure, TestRunResult, TraceFrame
from app.sandbox.models import ExecResult

GO_IMAGE = "bugfix-sandbox-go:latest"

_SKIP_DIRS = {".git", "vendor", "node_modules", "__pycache__"}

# `--- FAIL: TestDivide (0.00s)` / `    --- PASS: TestX/sub (0.00s)` (subtests indent).
_RESULT_RE = re.compile(r"^\s*--- (?P<kind>PASS|FAIL|SKIP): (?P<name>\S+) \(")
# `=== RUN   TestDivide`
_RUN_RE = re.compile(r"^\s*=== RUN\s+(?P<name>\S+)\s*$")
# A `file.go:line` token (test-log line, panic stack frame, or compile error).
_FILE_RE = re.compile(r"(?P<file>[\w./@+-]+\.go):(?P<line>\d+)")
# A panic-stack function line: `example/pkg.Func(0x..)` / `main.foo(...)`.
_FUNC_RE = re.compile(r"^(?P<fn>[\w./*()\[\]]+)\(")
# `# example/calc` — the header that precedes a compile error block.
_PKG_ERR_RE = re.compile(r"^# \S+")


def _relativize(file: str, root: str | Path | None) -> str:
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


def parse_frames(text: str, workspace: str | Path | None = None) -> list[TraceFrame]:
    """Extract ``file.go:line`` frames; attach the enclosing func from panic stacks."""
    frames: list[TraceFrame] = []
    last_func = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        fn = _FUNC_RE.match(line.strip())
        if fn is not None and ".go" not in line:
            last_func = fn.group("fn").split("(")[0]
        m = _FILE_RE.search(line)
        if m is None:
            continue
        frames.append(
            TraceFrame(
                file=_relativize(m.group("file"), workspace),
                line=int(m.group("line")),
                function=last_func,
            )
        )
        last_func = ""
    return frames


class GoTestAdapter:
    """Go via ``go test ./... -v`` (standard-library testing)."""

    framework = Framework.GO_TEST
    image = GO_IMAGE
    commands = frozenset({"go"})

    def detect(self, workspace: Path) -> bool:
        if (workspace / "go.mod").is_file():
            return True
        for path in workspace.rglob("*_test.go"):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            return True
        return False

    def install_command(self, workspace: Path) -> list[str] | None:
        if (workspace / "go.mod").is_file():
            return ["go", "mod", "download"]
        return None

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        if targets:
            return ["go", "test", "-v", *targets]
        return ["go", "test", "./...", "-v"]

    def parse_frames(self, text: str, workspace: str | Path | None = None) -> list[TraceFrame]:
        return parse_frames(text, workspace)

    def _failure_blocks(self, text: str) -> list[tuple[str, list[str]]]:
        """Return ``(test_name, body_lines)`` for each failing test.

        Body is the run-log between ``=== RUN Test`` and its ``--- FAIL:`` plus
        any trailing panic stack.
        """
        lines = text.splitlines()
        current_name: str | None = None
        buffer: list[str] = []
        blocks: list[tuple[str, list[str]]] = []
        for line in lines:
            run = _RUN_RE.match(line)
            if run is not None:
                current_name = run.group("name")
                buffer = []
                continue
            result = _RESULT_RE.match(line)
            if result is not None:
                if result.group("kind") == "FAIL":
                    blocks.append((result.group("name"), buffer))
                buffer = []
                current_name = None
                continue
            if current_name is not None:
                buffer.append(line)
        return blocks

    def _message(self, detail: list[str]) -> str:
        for line in detail:
            stripped = line.strip()
            if not stripped:
                continue
            # `calc_test.go:11: got X want Y` — drop the location prefix.
            m = _FILE_RE.match(stripped)
            if m is not None:
                rest = stripped[m.end() :].lstrip(": ").strip()
                if rest:
                    return rest
            if stripped.startswith("panic:"):
                return stripped
        for line in detail:
            if line.strip():
                return line.strip()
        return ""

    def parse_result(
        self, exec_result: ExecResult, workspace: str | Path | None = None
    ) -> TestRunResult:
        combined = exec_result.stdout + "\n" + exec_result.stderr
        passed = failed = skipped = 0
        for line in combined.splitlines():
            m = _RESULT_RE.match(line)
            if m is None:
                continue
            kind = m.group("kind")
            if kind == "PASS":
                passed += 1
            elif kind == "FAIL":
                failed += 1
            else:
                skipped += 1

        failures: list[TestFailure] = []
        errors = 0

        if exec_result.timed_out:
            outcome = Outcome.TIMEOUT
        elif failed > 0:
            outcome = Outcome.FAILED
            for name, detail in self._failure_blocks(combined):
                body = "\n".join(detail)
                failures.append(
                    TestFailure(
                        nodeid=name,
                        message=self._message(detail),
                        frames=parse_frames(body, workspace),
                    )
                )
        elif exec_result.returncode != 0:
            # No test failures but a non-zero exit → compile/build error.
            outcome = Outcome.ERROR
            errors = 1
            failures.append(
                TestFailure(
                    nodeid="build",
                    message=self._compile_message(combined),
                    frames=parse_frames(combined, workspace),
                )
            )
        elif passed == 0:
            outcome = Outcome.NO_TESTS
        else:
            outcome = Outcome.PASSED

        return TestRunResult(
            framework=self.framework,
            outcome=outcome,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            failures=failures,
            duration_s=exec_result.duration_s,
            returncode=exec_result.returncode,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
        )

    def _compile_message(self, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if _PKG_ERR_RE.match(stripped):
                continue
            if _FILE_RE.search(stripped) and ":" in stripped:
                return stripped
        return "build failed"
