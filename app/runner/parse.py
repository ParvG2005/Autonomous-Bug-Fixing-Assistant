"""Parse pytest's text output into a :class:`TestRunResult`.

We drive pytest with ``-q --tb=native -rfE`` (see :mod:`app.runner.pytest_runner`),
which gives us three things to parse:

* a summary line — ``=== 1 failed, 2 passed, 1 skipped in 0.04s ===`` — for counts;
* a "short test summary info" section — ``FAILED nodeid - ExcType: msg`` /
  ``ERROR nodeid - ...`` — for stable node ids and messages;
* per-failure native tracebacks under ``____ name ____`` headers — for frames.

The pieces are stitched together: tracebacks are matched to summary entries by
node-id suffix, falling back to positional order.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.runner.models import Outcome, TestFailure, TraceFrame
from app.runner.trace import parse_exception_message, parse_frames

# The summary line — `=== 1 failed, 2 passed in 0.04s ===` or, when pytest's
# output is captured/narrow, the bare `1 failed, 2 passed in 0.04s`. Keyed on the
# trailing `in <n>s` duration so banners (`==== FAILURES ====`) never match.
_DURATION_RE = re.compile(r"\bin \d[\d.]*s\b")
_COUNT_RE = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)")
# `____ test_divide ____` or `____ ERROR collecting tests/test_x.py ____`
_HEADER_RE = re.compile(r"^_{3,} (?P<name>.+?) _{3,}$")
# `FAILED tests/test_x.py::test_divide - ZeroDivisionError: division by zero`
_SUMMARY_ENTRY_RE = re.compile(r"^(?P<kind>FAILED|ERROR) (?P<nodeid>\S+)(?: - (?P<msg>.*))?$")


def parse_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in text.splitlines():
        body = line.strip().strip("=").strip()
        # Only the run-summary line carries a trailing duration; this excludes
        # banners and short-summary entries (`FAILED nodeid - ...`).
        if not _DURATION_RE.search(body):
            continue
        for num, word in _COUNT_RE.findall(body):
            key = "errors" if word == "error" else word
            counts[key] = int(num)
    return counts


def _summary_entries(text: str) -> list[tuple[str, str, str]]:
    """Return ``(kind, nodeid, message)`` from the short test summary section."""
    entries: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        m = _SUMMARY_ENTRY_RE.match(line.strip())
        if m is None:
            continue
        entries.append((m.group("kind"), m.group("nodeid"), (m.group("msg") or "").strip()))
    return entries


def _failure_blocks(text: str) -> list[tuple[str, str]]:
    """Split the FAILURES/ERRORS region into ``(header_name, body_text)`` blocks."""
    lines = text.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in lines:
        header = _HEADER_RE.match(line)
        if header is not None:
            current = []
            blocks.append((header.group("name").strip(), current))
            continue
        if current is None:
            continue
        # Stop a block when the trailing summary banner begins.
        if line.startswith("=") and (
            " short test summary " in line or line.strip("= ").endswith("s")
        ):
            current = None
            continue
        current.append(line)
    return [(name, "\n".join(body)) for name, body in blocks]


def _match_nodeid(header: str, entries: list[tuple[str, str, str]], used: set[int]) -> int | None:
    token = header.split(".")[-1].split(" ")[-1]
    for i, (_kind, nodeid, _msg) in enumerate(entries):
        if i in used:
            continue
        tail = nodeid.split("::")[-1]
        if tail == token or header in nodeid or nodeid.endswith(header.replace(".", "::")):
            return i
    return None


def build_failures(text: str, workspace: str | Path | None = None) -> list[TestFailure]:
    """Reconstruct the list of failing/erroring tests with frames + messages.

    ``workspace`` is the relativization root (the workspace's mount point inside
    the run environment); see :func:`app.runner.trace._relativize`.
    """
    entries = _summary_entries(text)
    blocks = _failure_blocks(text)
    failures: list[TestFailure] = []
    used: set[int] = set()

    for pos, (header, body) in enumerate(blocks):
        frames: list[TraceFrame] = parse_frames(body, workspace)
        if workspace is not None:
            # `--tb=native` includes pytest/pluggy/stdlib frames; keep only the
            # user's repo frames (those that relativized to a workspace path) so
            # localization points at the code under test, not the framework.
            in_workspace = [f for f in frames if not Path(f.file).is_absolute()]
            if in_workspace:
                frames = in_workspace
        idx = _match_nodeid(header, entries, used)
        if idx is None and pos < len(entries) and pos not in used:
            idx = pos  # positional fallback: blocks and entries share order
        if idx is not None and idx not in used:
            used.add(idx)
            _kind, nodeid, msg = entries[idx]
        else:
            nodeid, msg = header, ""
        message = msg or parse_exception_message(body)
        failures.append(TestFailure(nodeid=nodeid, message=message, frames=frames))

    # Summary entries with no traceback block (rare) still count as failures.
    for i, (_kind, nodeid, msg) in enumerate(entries):
        if i not in used:
            failures.append(TestFailure(nodeid=nodeid, message=msg, frames=[]))
    return failures


def decide_outcome(counts: dict[str, int], returncode: int) -> Outcome:
    """Map counts + pytest's exit code to an :class:`Outcome`.

    pytest exit codes: 0=all passed, 1=tests failed, 2=interrupted,
    3=internal error, 4=usage error, 5=no tests collected.
    """
    if counts.get("errors", 0) > 0 or returncode in (2, 3, 4):
        return Outcome.ERROR
    if counts.get("failed", 0) > 0:
        return Outcome.FAILED
    if returncode == 5 or (counts.get("passed", 0) == 0 and not counts):
        return Outcome.NO_TESTS
    if counts.get("passed", 0) == 0 and counts.get("skipped", 0) == 0:
        return Outcome.NO_TESTS
    return Outcome.PASSED
