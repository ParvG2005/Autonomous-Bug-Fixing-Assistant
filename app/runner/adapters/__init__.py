"""Language-adapter registry (Phase 8).

The runner is multi-language: each :class:`~app.runner.adapters.base.LanguageAdapter`
knows how to detect, install, run, and parse one language's tests. The registry
is an ordered list; :func:`detect_adapter` returns the first adapter that claims
a workspace (Python first, so existing single-language behavior is unchanged).
"""

from __future__ import annotations

from pathlib import Path

from app.runner.adapters.base import LanguageAdapter
from app.runner.adapters.golang import GoTestAdapter
from app.runner.adapters.javascript import NodeTestAdapter
from app.runner.adapters.python import PytestAdapter
from app.runner.models import Framework, TraceFrame

# Order matters: the first adapter whose ``detect`` is true wins. Python leads so
# a Python repo never even scans for JS/Go test files.
ADAPTERS: list[LanguageAdapter] = [PytestAdapter(), NodeTestAdapter(), GoTestAdapter()]

_BY_FRAMEWORK: dict[Framework, LanguageAdapter] = {a.framework: a for a in ADAPTERS}


def detect_adapter(workspace: Path) -> LanguageAdapter | None:
    """Return the adapter for ``workspace``, or ``None`` if none matches."""
    workspace = workspace.resolve()
    if not workspace.is_dir():
        return None
    for adapter in ADAPTERS:
        if adapter.detect(workspace):
            return adapter
    return None


def adapter_for(framework: Framework) -> LanguageAdapter:
    """Return the adapter implementing ``framework`` (raises ``KeyError`` if none)."""
    return _BY_FRAMEWORK[framework]


def parse_any_frames(text: str, workspace: str | Path | None = None) -> list[TraceFrame]:
    """Parse stack frames out of ``text`` trying each language in registry order.

    Returns the first non-empty result so an issue carrying a Python traceback,
    a Node stack, or a Go panic all yield frames. Used by issue parsing, which
    sees text before any workspace is known.
    """
    for adapter in ADAPTERS:
        frames = adapter.parse_frames(text, workspace)
        if frames:
            return frames
    return []


__all__ = [
    "ADAPTERS",
    "GoTestAdapter",
    "LanguageAdapter",
    "NodeTestAdapter",
    "PytestAdapter",
    "adapter_for",
    "detect_adapter",
    "parse_any_frames",
]
