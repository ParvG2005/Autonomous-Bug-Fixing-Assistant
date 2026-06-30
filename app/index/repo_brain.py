"""``RepoBrain``: the facade the agent (and the CLI) query.

Bundles the workspace, the symbol index, and the read/search tools, and
implements ``find_symbol`` as the union of exact definitions (tree-sitter) and
usages (ripgrep word-search). Optionally consults a vector backend as a
fallback when lexical search comes up empty.
"""

from __future__ import annotations

from pathlib import Path

from app.index.models import SearchHit, Symbol, SymbolLookup
from app.index.read import FileSlice, read_file
from app.index.retrieval import VectorBackend
from app.index.search import search
from app.index.symbols import SymbolIndex


class RepoBrain:
    """Read-only knowledge layer over one cloned workspace."""

    def __init__(self, root: Path, *, vector_backend: VectorBackend | None = None) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"workspace {self.root} is not a directory")
        self._index = SymbolIndex.build(self.root)
        self._vector = vector_backend

    @property
    def symbol_count(self) -> int:
        return len(self._index)

    # --- agent tools -----------------------------------------------------

    def read_file(
        self, rel_path: str, *, start_line: int = 1, end_line: int | None = None
    ) -> FileSlice:
        """Read a workspace file (1-based, inclusive range)."""
        return read_file(self.root, rel_path, start_line=start_line, end_line=end_line)

    def search(self, pattern: str, *, word: bool = False, fixed: bool = False) -> list[SearchHit]:
        """Lexical search across the workspace via ripgrep."""
        return search(pattern, self.root, word=word, fixed=fixed)

    def find_symbol(self, name: str) -> SymbolLookup:
        """Answer "where is ``name`` defined / used".

        Definitions come from the exact tree-sitter index; usages come from a
        word-boundary ripgrep over Python files. If both are empty and a vector
        backend is configured, fall back to semantic search for usages.
        """
        definitions: list[Symbol] = self._index.definitions(name)
        usages: list[SearchHit] = self.search(name, word=True)

        if not definitions and not usages and self._vector is not None:
            usages = self._vector.similar(name)

        return SymbolLookup(name=name, definitions=definitions, usages=usages)
