"""Hybrid retrieval: ripgrep-led, vector fallback.

Lexical search (ripgrep + symbol index) is primary and always available. Vector
search over pgvector chunk embeddings is the *fallback* for when lexical search
misses (semantic queries, renamed concepts). Per cut-order #4 it is the last
thing cut, so it lives behind an optional protocol: if pgvector isn't installed
or configured, the brain degrades cleanly to lexical-only.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.index.models import SearchHit


@runtime_checkable
class VectorBackend(Protocol):
    """Minimal contract a semantic backend must satisfy.

    Phase 1 ships the interface, not an implementation; wiring pgvector +
    embeddings is deferred (it needs Postgres). The brain checks for a backend
    at runtime and skips the fallback when absent.
    """

    def similar(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Return chunks semantically similar to ``query``."""
        ...
