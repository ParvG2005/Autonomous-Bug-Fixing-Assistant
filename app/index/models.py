"""Value types shared across the repo-brain tools.

Locations are workspace-relative and 1-based on line/column so they map cleanly
to what an editor and a stack trace report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SymbolKind(StrEnum):
    """Kinds of definition the symbol index understands (Python first)."""

    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"


@dataclass(frozen=True)
class Location:
    """A workspace-relative source location (1-based line/column)."""

    path: str
    line: int
    column: int = 1
    end_line: int | None = None

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Symbol:
    """A definition discovered by the tree-sitter index."""

    name: str
    kind: SymbolKind
    location: Location
    # For methods: the enclosing class name. None for module-level symbols.
    parent: str | None = None

    @property
    def qualified_name(self) -> str:
        """``Class.method`` for methods, otherwise the bare name."""
        return f"{self.parent}.{self.name}" if self.parent else self.name


@dataclass(frozen=True)
class SearchHit:
    """A single ripgrep match line."""

    location: Location
    text: str

    def __str__(self) -> str:
        return f"{self.location}  {self.text.strip()}"


@dataclass
class SymbolLookup:
    """Answer to "where is X defined / used"."""

    name: str
    definitions: list[Symbol] = field(default_factory=list)
    usages: list[SearchHit] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.definitions or self.usages)
