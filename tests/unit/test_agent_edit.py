"""Unit tests for the edit_file tool and diff rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.edit import EditError, apply_edit, unified_diff
from app.index.read import PathOutsideWorkspace


def test_apply_edit_unique_replacement(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    edit = apply_edit(tmp_path, "m.py", "return 1", "return 2")
    assert (tmp_path / "m.py").read_text() == "def f():\n    return 2\n"
    assert edit.before != edit.after


def test_apply_edit_creates_new_file(tmp_path: Path) -> None:
    edit = apply_edit(tmp_path, "pkg/new.py", "", "x = 1\n")
    assert (tmp_path / "pkg" / "new.py").read_text() == "x = 1\n"
    assert edit.before == ""


def test_apply_edit_refuses_clobber(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("a\n", encoding="utf-8")
    with pytest.raises(EditError):
        apply_edit(tmp_path, "m.py", "", "b\n")


def test_apply_edit_rejects_missing_match(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("a\n", encoding="utf-8")
    with pytest.raises(EditError):
        apply_edit(tmp_path, "m.py", "zzz", "b")


def test_apply_edit_rejects_ambiguous_match(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("x\nx\n", encoding="utf-8")
    with pytest.raises(EditError):
        apply_edit(tmp_path, "m.py", "x", "y")


def test_apply_edit_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspace):
        apply_edit(tmp_path, "../escape.py", "", "x")


def test_unified_diff_coalesces_same_file(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("a = 1\n", encoding="utf-8")
    e1 = apply_edit(tmp_path, "m.py", "a = 1", "a = 2")
    e2 = apply_edit(tmp_path, "m.py", "a = 2", "a = 3")
    diff = unified_diff([e1, e2])
    # Net change is 1 -> 3; the intermediate 2 should not appear.
    assert "-a = 1" in diff
    assert "+a = 3" in diff
    assert "a = 2" not in diff
