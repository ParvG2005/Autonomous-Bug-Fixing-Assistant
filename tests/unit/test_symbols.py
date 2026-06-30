"""Tree-sitter symbol index: functions, methods, classes, and locations."""

from __future__ import annotations

from pathlib import Path

from app.index.models import SymbolKind
from app.index.symbols import SymbolIndex


def test_indexes_functions_classes_and_methods(workspace: Path) -> None:
    index = SymbolIndex.build(workspace)

    kinds = {(s.name, s.kind, s.parent) for s in index.all_symbols()}
    assert ("greet", SymbolKind.FUNCTION, None) in kinds  # module-level function
    assert ("Greeter", SymbolKind.CLASS, None) in kinds
    assert ("greet", SymbolKind.METHOD, "Greeter") in kinds  # method, distinct from function
    assert ("__init__", SymbolKind.METHOD, "Greeter") in kinds
    assert ("shout", SymbolKind.FUNCTION, None) in kinds


def test_definitions_lookup_returns_both_function_and_method(workspace: Path) -> None:
    index = SymbolIndex.build(workspace)
    greets = index.definitions("greet")
    # one module function + one method share the name 'greet'
    assert {s.kind for s in greets} == {SymbolKind.FUNCTION, SymbolKind.METHOD}


def test_method_qualified_name_and_location(workspace: Path) -> None:
    index = SymbolIndex.build(workspace)
    method = next(s for s in index.definitions("greet") if s.kind is SymbolKind.METHOD)
    assert method.qualified_name == "Greeter.greet"
    assert method.location.path == "sample.py"
    assert method.location.line > 0
