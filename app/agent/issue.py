"""Parse free-form issue text or a stack trace into a structured task.

Phase 4 begins with an issue: a GitHub issue body, a bug report, or a raw stack
trace. :func:`parse_issue` pulls out the signals an agent needs to localize and
fix the bug — the exception type/message, the native-traceback frames (reusing
the Phase 2 parser), the referenced files and pytest node ids, and the candidate
identifiers (function/class names) mentioned in prose — and packages them as an
:class:`IssueTask` the loop can render into a prompt.

Parsing is deliberately lexical and conservative: it never guesses an exception
when the text contains no traceback, so a plain feature-style report doesn't get
a spurious ``error_type``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.runner.models import TraceFrame
from app.runner.trace import parse_frames

# `ExceptionType: message` — an exception class (ends in Error/Exception/Warning)
# flush against a message. The type may be dotted (``socket.timeout`` style names
# are rare; we accept dotted names ending in the usual suffixes).
_EXC_LINE_RE = re.compile(
    r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning))(?::\s*(?P<msg>.*))?$"
)
# A pytest node id: ``path/to/test_x.py::test_y`` (optionally parametrized).
_NODEID_RE = re.compile(r"[\w./-]+\.py::[\w:.\[\]\- ]+")
# A bare Python source path token.
_PYPATH_RE = re.compile(r"[\w./-]+\.py")
# A backticked code span.
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# A call expression ``name(`` or dotted ``a.b(``.
_CALL_RE = re.compile(r"\b([A-Za-z_][\w.]*)\s*\(")
_IDENT_RE = re.compile(r"^[A-Za-z_][\w.]*$")


@dataclass(frozen=True)
class IssueTask:
    """A bug report distilled into the signals the agent loop consumes."""

    title: str
    body: str
    error_type: str = ""
    error_message: str = ""
    frames: list[TraceFrame] = field(default_factory=list)
    referenced_paths: list[str] = field(default_factory=list)
    test_nodeids: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)

    @property
    def has_traceback(self) -> bool:
        """True when the issue carried a parseable native traceback."""
        return bool(self.frames or self.error_type)

    def to_prompt(self) -> str:
        """Render the task for the agent: the report plus the extracted signals."""
        parts = [f"Issue: {self.title}", "", self.body.strip()]
        if self.error_message:
            parts += ["", f"Exception: {self.error_message}"]
        if self.frames:
            parts.append("")
            parts.append("Traceback frames (outermost first):")
            parts += [f"  {frame}" for frame in self.frames]
        if self.test_nodeids:
            parts += ["", "Referenced tests: " + ", ".join(self.test_nodeids)]
        return "\n".join(parts)


def _dedupe(items: list[str]) -> list[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_exception(text: str) -> tuple[str, str]:
    """Return ``(error_type, error_message)`` for the last exception-looking line.

    Only flush-left lines are considered, so an exception named mid-sentence in
    prose does not masquerade as the failing exception.
    """
    error_type = ""
    error_message = ""
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t"):  # indented → traceback body / prose, skip
            continue
        m = _EXC_LINE_RE.match(raw.strip())
        if m is None:
            continue
        error_type = m.group("type")
        error_message = raw.strip()
    return error_type, error_message


def _extract_identifiers(text: str) -> list[str]:
    """Candidate symbol names from backticked spans and call expressions."""
    found: list[str] = []
    for span in _BACKTICK_RE.findall(text):
        token = span.strip().rstrip("()")
        if _IDENT_RE.match(token):
            found.append(token)
    found += _CALL_RE.findall(text)
    return _dedupe(found)


def parse_issue(text: str, *, title: str | None = None) -> IssueTask:
    """Distill ``text`` into an :class:`IssueTask`.

    ``title`` overrides the heuristic (first non-empty line) when the caller
    already has a separate title (e.g. a GitHub issue title vs. body).
    """
    lines = text.splitlines()
    if title is None:
        title = next((ln.strip() for ln in lines if ln.strip()), "")
        body = "\n".join(lines[1:]) if lines else ""
    else:
        body = text

    error_type, error_message = _extract_exception(text)
    frames = parse_frames(text)

    nodeids = _dedupe(_NODEID_RE.findall(text))
    # Paths that are part of a node id should not also count as bare paths.
    nodeid_paths = {nid.split("::", 1)[0] for nid in nodeids}
    paths = [p for p in _dedupe(_PYPATH_RE.findall(text)) if p not in nodeid_paths]

    return IssueTask(
        title=title,
        body=body,
        error_type=error_type,
        error_message=error_message,
        frames=frames,
        referenced_paths=paths,
        test_nodeids=nodeids,
        identifiers=_extract_identifiers(text),
    )
