"""ripgrep search and the read_file tool, including path-traversal safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.index.read import PathOutsideWorkspace, read_file
from app.index.search import search


def test_search_finds_word_matches_across_files(workspace: Path) -> None:
    hits = search("greet", workspace, word=True, globs=["*.py"])
    paths = {h.location.path for h in hits}
    assert {"sample.py", "other.py"} <= paths
    assert all(h.location.line > 0 for h in hits)


def test_search_no_matches_returns_empty(workspace: Path) -> None:
    assert search("definitely_not_present_xyz", workspace) == []


def test_read_file_full_and_range(workspace: Path) -> None:
    full = read_file(workspace, "sample.py")
    assert "def greet" in full.text

    sliced = read_file(workspace, "sample.py", start_line=1, end_line=1)
    assert sliced.start_line == 1
    assert sliced.end_line == 1
    assert sliced.text.startswith('"""')


def test_read_file_rejects_path_traversal(workspace: Path) -> None:
    with pytest.raises(PathOutsideWorkspace):
        read_file(workspace, "../../etc/passwd")


@pytest.mark.parametrize("rel", ["", ".", "subdir"])
def test_read_file_on_directory_raises_clean_not_found(workspace: Path, rel: str) -> None:
    # A directory (including the workspace root via "" / ".") must not surface a
    # raw IsADirectoryError, which the agent loop does not catch and which crashes
    # the whole job. It must be a FileNotFoundError the tool layer can recover from.
    (workspace / "subdir").mkdir()
    with pytest.raises(FileNotFoundError):
        read_file(workspace, rel)
