"""Rank suspect files for a bug from an :class:`IssueTask` and the repo brain.

Localization fuses three lexical signals, strongest first:

1. **Traceback frames** that fall inside the workspace — the most direct evidence
   of where execution failed; the innermost in-workspace frame is weighted highest.
2. **Referenced paths** named in the issue that actually exist in the workspace.
3. **Identifiers** (function/class names) mentioned in prose, resolved to their
   defining files via the tree-sitter symbol index.

Scores accumulate per file; ties break on first-seen order, which keeps results
deterministic. This is intentionally not semantic — it gives the agent a ranked
starting set to read, not a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.issue import IssueTask
from app.index.repo_brain import RepoBrain

# Signal weights (relative, not calibrated to anything external).
_W_FRAME_INNERMOST = 5.0
_W_FRAME_OTHER = 3.0
_W_REFERENCED_PATH = 2.5
_W_SYMBOL_DEF = 2.0
# Test files are unlikely fix sites; nudge them down so source ranks above tests.
_TEST_PENALTY = 4.0


@dataclass
class Suspect:
    """A candidate file to inspect, with an explanation of why."""

    path: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def add(self, weight: float, reason: str) -> None:
        self.score += weight
        self.reasons.append(reason)


def _looks_like_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}"


def rank_suspects(brain: RepoBrain, task: IssueTask, *, limit: int = 10) -> list[Suspect]:
    """Return suspect files for ``task``, highest score first (capped at ``limit``)."""
    suspects: dict[str, Suspect] = {}

    def get(path: str) -> Suspect:
        return suspects.setdefault(path, Suspect(path=path))

    def exists(path: str) -> bool:
        try:
            return (brain.root / path).is_file()
        except (OSError, ValueError):
            return False

    # 1. Traceback frames inside the workspace. The last frame is innermost.
    in_ws = [f for f in task.frames if not f.file.startswith("/") and exists(f.file)]
    for i, frame in enumerate(in_ws):
        innermost = i == len(in_ws) - 1
        weight = _W_FRAME_INNERMOST if innermost else _W_FRAME_OTHER
        get(frame.file).add(weight, f"traceback frame at line {frame.line} in {frame.function}")

    # 2. Paths named in the issue that exist.
    for path in task.referenced_paths:
        if exists(path):
            get(path).add(_W_REFERENCED_PATH, "named in the issue")

    # 3. Identifiers resolved to their defining files.
    for ident in task.identifiers:
        name = ident.rsplit(".", 1)[-1]  # ``Class.method`` → ``method``
        lookup = brain.find_symbol(name)
        for sym in lookup.definitions:
            get(sym.location.path).add(_W_SYMBOL_DEF, f"defines {sym.qualified_name}")

    for suspect in suspects.values():
        if _looks_like_test(suspect.path):
            suspect.score -= _TEST_PENALTY

    ranked = sorted(suspects.values(), key=lambda s: -s.score)
    return ranked[:limit]
