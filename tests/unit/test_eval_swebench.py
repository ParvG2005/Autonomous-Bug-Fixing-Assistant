"""Offline tests for the SWE-bench-lite loader (parse + fake-git materialize)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from eval.swebench import (
    load_instances,
    load_swebench_lite,
    materialize_instance,
)

_ROW = {
    "instance_id": "acme__widget-42",
    "repo": "acme/widget",
    "base_commit": "deadbeef",
    "problem_statement": "  Widget.frobnicate() crashes on empty input.  ",
    "test_patch": "diff --git a/test_w.py b/test_w.py\n",
}


def _jsonl(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "swe.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_load_instances_parses_and_strips(tmp_path: Path) -> None:
    insts = load_instances(_jsonl(tmp_path, [_ROW]))
    assert len(insts) == 1
    assert insts[0].instance_id == "acme__widget-42"
    assert insts[0].repo == "acme/widget"
    assert insts[0].issue_text() == "Widget.frobnicate() crashes on empty input."


def test_load_instances_respects_limit(tmp_path: Path) -> None:
    rows = [{**_ROW, "instance_id": f"i{i}"} for i in range(5)]
    assert len(load_instances(_jsonl(tmp_path, rows), limit=2)) == 2


def test_missing_dataset_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="SWE-bench-lite dataset not found"):
        load_instances(tmp_path / "nope.jsonl")


def test_load_swebench_lite_builds_cases_with_setup(tmp_path: Path) -> None:
    cases = load_swebench_lite(_jsonl(tmp_path, [_ROW]))
    assert len(cases) == 1
    assert cases[0].id == "acme__widget-42"
    assert cases[0].setup is not None  # clone-backed, not inline files


def test_materialize_instance_drives_git_without_network(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, cwd=None, capture_output=False):  # type: ignore[no-untyped-def]
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    insts = load_instances(_jsonl(tmp_path, [_ROW]))
    materialize_instance(insts[0], tmp_path / "ws", run=fake_run)

    joined = [" ".join(c) for c in calls]
    assert any("git init" in j for j in joined)
    assert any("acme/widget.git" in j for j in joined)
    assert any("fetch" in j and "deadbeef" in j for j in joined)
    assert any("checkout" in j and "FETCH_HEAD" in j for j in joined)
    assert any(j.startswith("git apply") for j in joined)


def test_materialize_instance_surfaces_git_failure(tmp_path: Path) -> None:
    def fail_run(argv, cwd=None, capture_output=False):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(argv, 1, b"", b"boom")

    insts = load_instances(_jsonl(tmp_path, [_ROW]))
    with pytest.raises(RuntimeError, match=r"git .* failed"):
        materialize_instance(insts[0], tmp_path / "ws", run=fail_run)
