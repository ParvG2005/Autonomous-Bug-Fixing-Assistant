"""``read_file`` tool: read workspace files safely.

Path traversal is the obvious attack (repo content is untrusted), so every read
is confined to the workspace root. Optional line ranges keep large files out of
the model context.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PathOutsideWorkspace(Exception):
    """Raised when a requested path escapes the workspace root."""


@dataclass(frozen=True)
class FileSlice:
    """A (possibly partial) view of a file."""

    path: str
    start_line: int
    end_line: int
    text: str


def resolve_in_workspace(root: Path, rel_path: str | Path) -> Path:
    """Resolve ``rel_path`` against ``root``, rejecting anything that escapes it."""
    root_resolved = root.resolve()
    candidate = (root_resolved / rel_path).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PathOutsideWorkspace(f"{rel_path!r} resolves outside the workspace")
    return candidate


def read_file(
    root: Path,
    rel_path: str | Path,
    *,
    start_line: int = 1,
    end_line: int | None = None,
) -> FileSlice:
    """Read ``rel_path`` (1-based, inclusive line range) from the workspace."""
    if start_line < 1:
        raise ValueError("start_line is 1-based and must be >= 1")
    path = resolve_in_workspace(root, rel_path)
    if not path.is_file():
        # A directory (or the workspace root, when rel_path is "" / ".") would
        # raise a raw IsADirectoryError that the agent loop doesn't catch and that
        # crashes the job. Surface a recoverable FileNotFoundError instead.
        raise FileNotFoundError(f"{Path(rel_path)!s} is not a file in the workspace")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    last = len(lines) if end_line is None else min(end_line, len(lines))
    selected = lines[start_line - 1 : last]
    return FileSlice(
        path=str(Path(rel_path)),
        start_line=start_line,
        end_line=start_line - 1 + len(selected),
        text="\n".join(selected),
    )
