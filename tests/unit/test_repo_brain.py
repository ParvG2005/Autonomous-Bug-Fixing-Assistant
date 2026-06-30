"""RepoBrain.find_symbol: the Phase 1 acceptance behavior in unit form."""

from __future__ import annotations

from pathlib import Path

from app.index.models import SearchHit, SymbolKind
from app.index.repo_brain import RepoBrain


def test_find_symbol_reports_definitions_and_usages(workspace: Path) -> None:
    brain = RepoBrain(workspace)
    result = brain.find_symbol("greet")

    assert result.found
    # defined as both a function and a method
    assert {d.kind for d in result.definitions} == {SymbolKind.FUNCTION, SymbolKind.METHOD}
    # used in both files
    usage_paths = {u.location.path for u in result.usages}
    assert {"sample.py", "other.py"} <= usage_paths


def test_find_symbol_unknown_is_empty(workspace: Path) -> None:
    brain = RepoBrain(workspace)
    result = brain.find_symbol("no_such_symbol")
    assert not result.found
    assert result.definitions == []
    assert result.usages == []


def test_vector_backend_used_only_as_fallback(workspace: Path) -> None:
    calls: list[str] = []

    class FakeVector:
        def similar(self, query: str, *, limit: int = 10) -> list[SearchHit]:
            calls.append(query)
            return []

    brain = RepoBrain(workspace, vector_backend=FakeVector())

    # lexical hit -> vector NOT consulted
    brain.find_symbol("greet")
    assert calls == []

    # lexical miss -> vector consulted
    brain.find_symbol("no_such_symbol")
    assert calls == ["no_such_symbol"]
