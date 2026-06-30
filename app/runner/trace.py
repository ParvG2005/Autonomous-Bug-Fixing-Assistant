"""Stack-trace parser → ``{file, line, function}`` frames.

We run pytest with ``--tb=native`` (see :mod:`app.runner.pytest_runner`) so every
traceback is a standard CPython one::

    Traceback (most recent call last):
      File "/workspace/pkg/mod.py", line 12, in divide
        return a / b
    ZeroDivisionError: division by zero

This module pulls the ``File "...", line N, in func`` frames out of such text and,
when a frame's path lives inside the workspace, rewrites it workspace-relative so
frames line up with what the repo brain and editor report.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from app.runner.models import TraceFrame

# `  File "path", line N, in func`
_FRAME_RE = re.compile(r'^\s*File "(?P<file>.+?)", line (?P<line>\d+), in (?P<func>.+?)\s*$')
# The final `ExceptionType: message` line of a native traceback (not indented).
_EXC_RE = re.compile(r"^(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Failed|Failure)\b.*)$")


def _relativize(file: str, root: str | Path | None) -> str:
    """Strip ``root`` from an absolute frame path (pure prefix, no filesystem).

    ``root`` is where the workspace lives inside the run environment — the host
    workspace path for the local sandbox, ``/workspace`` for the Docker sandbox.
    Paths outside ``root`` (stdlib, site-packages) are left absolute.
    """
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
    """Extract all native-traceback frames from ``text`` in source order.

    ``workspace`` is the relativization root (see :func:`_relativize`); frames
    inside it become workspace-relative, others stay absolute.
    """
    frames: list[TraceFrame] = []
    for line in text.splitlines():
        m = _FRAME_RE.match(line)
        if m is None:
            continue
        frames.append(
            TraceFrame(
                file=_relativize(m.group("file"), workspace),
                line=int(m.group("line")),
                function=m.group("func").strip(),
            )
        )
    return frames


def parse_exception_message(text: str) -> str:
    """Best-effort extraction of the exception line from a native traceback.

    Returns the last line that looks like ``SomeError: ...``; falls back to the
    last non-empty line so the caller always gets something human-readable.
    """
    last_exc = ""
    last_nonempty = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        last_nonempty = line.strip()
        # Exception lines are flush-left (no leading whitespace).
        if line[:1] not in (" ", "\t") and _EXC_RE.match(line.strip()):
            last_exc = line.strip()
    return last_exc or last_nonempty
