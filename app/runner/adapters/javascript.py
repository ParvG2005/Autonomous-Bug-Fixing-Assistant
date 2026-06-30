"""JavaScript / TypeScript adapter — Node's built-in test runner.

We drive ``node --test`` rather than jest/vitest so the common case needs **no
dependency install** (the runner is built into Node ≥18, ships TAP output, and
auto-discovers ``*.test.js`` / ``*.spec.js`` under Node ≥20). Projects that use
jest/vitest still run via their ``npm test`` script once deps are installed, but
the zero-dep path is what keeps the offline acceptance honest.

TAP (Test Anything Protocol) output looks like::

    TAP version 13
    not ok 2 - divide by zero
      ---
      error: 'Expected values to be strictly equal:\\n\\n5 !== 6'
      stack: |-
        TestContext.<anonymous> (/workspace/calc.test.js:11:10)
      ...
    1..2
    # tests 2
    # pass 1
    # fail 1

Counts come from the ``# pass/fail/...`` footer; per-failure messages + frames
from each ``not ok`` block's YAML detail.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from app.runner.models import Framework, Outcome, TestFailure, TestRunResult, TraceFrame
from app.sandbox.models import ExecResult

NODE_IMAGE = "bugfix-sandbox-node:latest"

_TEST_SUFFIXES = (".test.js", ".test.mjs", ".test.cjs", ".test.ts", ".test.tsx", ".test.jsx")
_SPEC_SUFFIXES = (".spec.js", ".spec.mjs", ".spec.cjs", ".spec.ts", ".spec.tsx", ".spec.jsx")
_SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".next", "__pycache__"}

# `# pass 1` / `# fail 2` / `# tests 3` footer counts.
_COUNT_RE = re.compile(r"^#\s*(?P<key>tests|pass|fail|skipped|todo|cancelled)\s+(?P<n>\d+)\s*$")
# `not ok 2 - name` / `ok 1 - name` TAP result lines.
_RESULT_RE = re.compile(r"^(?P<ok>not ok|ok)\s+\d+\s*-\s*(?P<name>.*?)\s*$")
# A stack/location frame: optional `at `, optional `func (`, then `file:line[:col]`.
_FRAME_RE = re.compile(
    r"(?:at\s+)?(?:(?P<func>[\w$.<>\[\] ]+?)\s+\()?"
    r"(?P<file>[^\s()'\":]+\.(?:m?js|cjs|jsx|tsx?|ts)):(?P<line>\d+)(?::\d+)?\)?"
)


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
    """Extract V8/TAP stack frames (``func (file:line:col)`` / ``at file:line``)."""
    frames: list[TraceFrame] = []
    for raw in text.splitlines():
        line = raw.strip().rstrip("'\",")
        m = _FRAME_RE.search(line)
        if m is None:
            continue
        frames.append(
            TraceFrame(
                file=_relativize(m.group("file"), workspace),
                line=int(m.group("line")),
                function=(m.group("func") or "").strip() or "<anonymous>",
            )
        )
    return frames


class NodeTestAdapter:
    """JS/TS via ``node --test`` (TAP output, zero-dependency)."""

    framework = Framework.NODE_TEST
    image = NODE_IMAGE
    commands = frozenset({"node", "npm", "npx"})

    def detect(self, workspace: Path) -> bool:
        if (workspace / "package.json").is_file():
            return True
        for path in workspace.rglob("*"):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            name = path.name
            if path.is_dir() and name == "__tests__":
                return True
            if path.is_file() and (name.endswith(_TEST_SUFFIXES) or name.endswith(_SPEC_SUFFIXES)):
                return True
        return False

    def install_command(self, workspace: Path) -> list[str] | None:
        if (workspace / "package.json").is_file() and not (workspace / "node_modules").is_dir():
            return ["npm", "install"]
        return None

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        # Force the TAP reporter: the default flips to the human "spec" reporter
        # on a TTY, so pinning TAP keeps parsing deterministic everywhere.
        cmd = ["node", "--test", "--test-reporter=tap"]
        if targets:
            cmd += list(targets)
        return cmd

    def parse_frames(self, text: str, workspace: str | Path | None = None) -> list[TraceFrame]:
        return parse_frames(text, workspace)

    def _counts(self, text: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for line in text.splitlines():
            m = _COUNT_RE.match(line.strip())
            if m is None:
                continue
            key = {"pass": "passed", "fail": "failed"}.get(m.group("key"), m.group("key"))
            counts[key] = int(m.group("n"))
        return counts

    def _failure_blocks(self, text: str) -> list[tuple[str, list[str]]]:
        """Return ``(name, detail_lines)`` for each ``not ok`` result."""
        lines = text.splitlines()
        blocks: list[tuple[str, list[str]]] = []
        current: list[str] | None = None
        for line in lines:
            m = _RESULT_RE.match(line.strip())
            if m is not None:
                current = []
                if m.group("ok") == "not ok":
                    blocks.append((m.group("name"), current))
                continue
            if line.startswith("#") or line.strip().startswith("1.."):
                current = None
                continue
            if current is not None:
                current.append(line)
        return blocks

    def _message(self, detail: list[str]) -> str:
        for i, raw in enumerate(detail):
            stripped = raw.strip()
            if not stripped.startswith("error:"):
                continue
            inline = stripped[len("error:") :].strip()
            # Inline form: `error: 'msg'`. Block-scalar form: `error: |-` then the
            # message on the following, more-indented lines.
            if inline and inline not in ("|-", "|", ">", ">-"):
                return inline.strip("'\"").split("\\n")[0].strip()
            base = len(raw) - len(raw.lstrip())
            for nxt in detail[i + 1 :]:
                if not nxt.strip():
                    continue
                if len(nxt) - len(nxt.lstrip()) <= base:
                    break  # dedented back to a YAML key — block ended
                return nxt.strip().strip("'\"")
            return ""
        for line in detail:
            if line.strip() and not line.strip().startswith(("---", "...", "stack:", "code:")):
                return line.strip().strip("'\"")
        return ""

    def parse_result(
        self, exec_result: ExecResult, workspace: str | Path | None = None
    ) -> TestRunResult:
        combined = exec_result.stdout + "\n" + exec_result.stderr
        counts = self._counts(combined)
        failures: list[TestFailure] = []

        if exec_result.timed_out:
            outcome = Outcome.TIMEOUT
        elif counts.get("tests", 0) == 0:
            outcome = Outcome.NO_TESTS
        elif counts.get("failed", 0) > 0:
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
            outcome = Outcome.ERROR
        elif counts.get("passed", 0) == 0:
            outcome = Outcome.NO_TESTS
        else:
            outcome = Outcome.PASSED

        return TestRunResult(
            framework=self.framework,
            outcome=outcome,
            passed=counts.get("passed", 0),
            failed=counts.get("failed", 0),
            errors=0,
            skipped=counts.get("skipped", 0),
            failures=failures,
            duration_s=exec_result.duration_s,
            returncode=exec_result.returncode,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
        )
