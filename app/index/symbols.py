"""tree-sitter symbol index for Python.

Walks each ``.py`` file's syntax tree once and records every function, method,
and class definition with its location. This is the exact "where is X *defined*"
half of the repo brain; ripgrep supplies the "used" half.

Python is the first (and, per the build plan, only required) language. The
walker is structured so additional grammars slot in behind the same
:class:`SymbolIndex` interface.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from app.index.models import Location, Symbol, SymbolKind

_PY_LANGUAGE = Language(tspython.language())


def _parser() -> Parser:
    return Parser(_PY_LANGUAGE)


class SymbolIndex:
    """In-memory index of definitions across a workspace.

    Build once with :meth:`build`, then query by name. Keeps it simple and
    re-buildable rather than incremental; a repo brain is rebuilt per job.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._by_name: dict[str, list[Symbol]] = defaultdict(list)
        self._all: list[Symbol] = []

    @classmethod
    def build(cls, root: Path) -> SymbolIndex:
        """Parse every ``.py`` file under ``root`` and index its definitions."""
        index = cls(root)
        parser = _parser()
        for py_file in sorted(index.root.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in py_file.relative_to(index.root).parts):
                continue
            try:
                source = py_file.read_bytes()
            except OSError:
                continue
            tree = parser.parse(source)
            rel = str(py_file.relative_to(index.root))
            for symbol in _walk(tree.root_node, rel, parent=None):
                index._add(symbol)
        return index

    def _add(self, symbol: Symbol) -> None:
        self._by_name[symbol.name].append(symbol)
        self._all.append(symbol)

    def definitions(self, name: str) -> list[Symbol]:
        """All definitions matching ``name`` (bare name, not qualified)."""
        return list(self._by_name.get(name, ()))

    def all_symbols(self) -> list[Symbol]:
        return list(self._all)

    def __len__(self) -> int:
        return len(self._all)


_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache"}


def _walk(node: Node, rel_path: str, parent: str | None) -> Iterator[Symbol]:
    """Yield definitions in ``node``, tracking the enclosing class for methods."""
    for child in node.named_children:
        if child.type == "function_definition":
            name = _name_of(child)
            if name is not None:
                kind = SymbolKind.METHOD if parent is not None else SymbolKind.FUNCTION
                yield Symbol(
                    name=name,
                    kind=kind,
                    location=_location(child, rel_path),
                    parent=parent,
                )
            # Nested defs (closures) keep the current class context (None inside a function).
            yield from _walk(child, rel_path, parent=None)
        elif child.type == "class_definition":
            name = _name_of(child)
            if name is not None:
                yield Symbol(
                    name=name,
                    kind=SymbolKind.CLASS,
                    location=_location(child, rel_path),
                    parent=parent,
                )
                # Descend into the class body so methods get parent=class name.
                body = child.child_by_field_name("body")
                if body is not None:
                    yield from _walk(body, rel_path, parent=name)
        else:
            yield from _walk(child, rel_path, parent=parent)


def _name_of(node: Node) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None or name_node.text is None:
        return None
    return name_node.text.decode("utf-8")


def _location(node: Node, rel_path: str) -> Location:
    start_row, start_col = node.start_point
    end_row, _ = node.end_point
    return Location(
        path=rel_path,
        line=start_row + 1,
        column=start_col + 1,
        end_line=end_row + 1,
    )
