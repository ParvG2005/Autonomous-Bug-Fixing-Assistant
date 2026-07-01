"""Phase 1 acceptance: clone a real public repo and answer where X is defined.

Marked ``integration`` (network + git). Run explicitly:

    pytest -m integration

Deselected by default so the unit suite stays offline and fast.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.index.clone import clone_repo, fetch_pr_head
from app.index.models import SymbolKind
from app.index.repo_brain import RepoBrain

pytestmark = pytest.mark.integration

# Small, stable, pure-Python public repo.
_REPO = "https://github.com/tkem/cachetools"


def test_where_is_defined_on_real_repo(tmp_path: Path) -> None:
    ws = clone_repo(_REPO, tmp_path / "cachetools", depth=1)

    brain = RepoBrain(ws)
    assert brain.symbol_count > 0

    # cachetools defines an LRUCache class.
    result = brain.find_symbol("LRUCache")
    assert result.found
    assert any(d.kind is SymbolKind.CLASS and d.name == "LRUCache" for d in result.definitions)
    assert result.usages, "expected at least one usage of LRUCache"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_fetch_pr_head_checks_out_pull_ref(tmp_path: Path):
    # Build an origin repo with a commit on refs/pull/1/head.
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    (origin / "a.txt").write_text("base")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "base")
    (origin / "a.txt").write_text("pr-change")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "pr")
    _git(origin, "update-ref", "refs/pull/1/head", "HEAD")
    _git(origin, "checkout", "-q", "HEAD~1")  # leave main at base

    work = clone_repo(str(origin), tmp_path / "work", depth=0, ref="main")
    fetch_pr_head(work, 1)
    assert (work / "a.txt").read_text() == "pr-change"
