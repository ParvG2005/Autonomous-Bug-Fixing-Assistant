"""The ``edit_file`` tool: apply a single, unambiguous string replacement.

Modelled on the str-replace editor pattern: the agent supplies ``old_str`` (which
must occur **exactly once** in the file) and ``new_str``. Requiring a unique match
makes edits deterministic and refuses fuzzy, hard-to-review changes. Creating a
new file is supported when ``old_str`` is empty and the file does not yet exist.

Every path is confined to the workspace root (repo content is untrusted), reusing
the Phase 1 traversal guard.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from app.agent.models import FileEdit
from app.index.read import resolve_in_workspace


class EditError(Exception):
    """Raised when an edit cannot be applied unambiguously."""


def apply_edit(root: Path, rel_path: str, old_str: str, new_str: str) -> FileEdit:
    """Replace the unique occurrence of ``old_str`` with ``new_str`` in a file.

    * ``old_str`` empty and the file missing → create the file with ``new_str``.
    * ``old_str`` empty and the file exists → :class:`EditError` (refuse to clobber).
    * ``old_str`` absent, or present more than once → :class:`EditError`.

    Returns the :class:`FileEdit` record (before/after text) on success.
    """
    path = resolve_in_workspace(root, rel_path)

    if old_str == "":
        if path.exists():
            raise EditError(f"{rel_path!r} already exists; provide a non-empty old_str to edit it")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_str, encoding="utf-8")
        return FileEdit(path=rel_path, before="", after=new_str)

    if not path.is_file():
        raise EditError(f"{rel_path!r} does not exist")

    before = path.read_text(encoding="utf-8")
    count = before.count(old_str)
    if count == 0:
        raise EditError(f"old_str not found in {rel_path!r}")
    if count > 1:
        raise EditError(
            f"old_str occurs {count} times in {rel_path!r}; make it unique (add context)"
        )

    after = before.replace(old_str, new_str, 1)
    path.write_text(after, encoding="utf-8")
    return FileEdit(path=rel_path, before=before, after=after)


def unified_diff(edits: list[FileEdit]) -> str:
    """Render a unified diff over the *net* change of each edited file.

    Multiple edits to the same file are coalesced: the diff compares the file's
    original text (before the first edit) to its final text (after the last).
    """
    first_before: dict[str, str] = {}
    last_after: dict[str, str] = {}
    order: list[str] = []
    for edit in edits:
        if edit.path not in first_before:
            first_before[edit.path] = edit.before
            order.append(edit.path)
        last_after[edit.path] = edit.after

    chunks: list[str] = []
    for path in order:
        before = first_before[path]
        after = last_after[path]
        if before == after:
            continue
        diff = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        chunks.append("".join(diff))
    return "\n".join(chunks)
