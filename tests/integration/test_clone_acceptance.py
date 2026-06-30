"""Phase 1 acceptance: clone a real public repo and answer where X is defined.

Marked ``integration`` (network + git). Run explicitly:

    pytest -m integration

Deselected by default so the unit suite stays offline and fast.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.index.clone import clone_repo
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
