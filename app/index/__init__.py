"""Repo brain: clone, symbol index, search, and hybrid retrieval (Phase 1).

The read-only knowledge layer the agent queries to answer "where is X defined /
used". Primary retrieval is lexical (ripgrep) + the tree-sitter symbol index;
semantic vector search (``app.index.retrieval``) is an optional fallback.
"""

from app.index.models import Location, SearchHit, Symbol, SymbolKind, SymbolLookup
from app.index.repo_brain import RepoBrain

__all__ = [
    "Location",
    "RepoBrain",
    "SearchHit",
    "Symbol",
    "SymbolKind",
    "SymbolLookup",
]
