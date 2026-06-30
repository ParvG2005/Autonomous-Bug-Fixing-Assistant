"""Offline tests for the eval dataset loader + EvalCase.materialize."""

from __future__ import annotations

from pathlib import Path

import pytest
from eval.dataset import CUSTOM_SUITE, EvalCase, load_suite


def test_load_custom_suite_has_cases_sorted_by_dir() -> None:
    cases = load_suite(CUSTOM_SUITE)
    ids = [c.id for c in cases]
    assert ids == sorted(ids)
    assert "01-titleize" in ids
    # Every case carries issue text and at least one workspace file.
    for c in cases:
        assert c.issue_text.strip()
        assert c.files


def test_materialize_inline_files(tmp_path: Path) -> None:
    case = EvalCase(id="x", issue_text="boom", files={"pkg/a.py": "x = 1\n", "b.txt": "hi"})
    ws = case.materialize(tmp_path / "ws")
    assert (ws / "pkg" / "a.py").read_text() == "x = 1\n"
    assert (ws / "b.txt").read_text() == "hi"


def test_materialize_prefers_setup_callable(tmp_path: Path) -> None:
    seen: list[Path] = []
    case = EvalCase(id="x", issue_text="i", files={"ignored.py": "x"}, setup=seen.append)
    ws = case.materialize(tmp_path / "ws")
    assert seen == [ws]
    # files are NOT written when a setup callable is supplied
    assert not (ws / "ignored.py").exists()


def test_unknown_suite_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_suite("does-not-exist", root=tmp_path)


def test_malformed_case_raises(tmp_path: Path) -> None:
    suite = tmp_path / "s" / "bad"
    suite.mkdir(parents=True)
    (suite / "meta.json").write_text("{}", encoding="utf-8")  # no issue.md
    with pytest.raises(ValueError, match="malformed"):
        load_suite("s", root=tmp_path)
