"""The discovery :class:`Candidate` and its dedup :func:`fingerprint`.

A ``Candidate`` is what a detector emits — an *in-memory*, pre-persistence
hypothesis about a bug. It is deliberately distinct from the ORM
:class:`~app.models.entities.Finding` (the persisted row): a candidate is cheap
and noisy; only after dedup + (eventually) reproduction does it earn a row.

A candidate renders to issue text via :meth:`Candidate.render_issue`, which is
the whole trick — the rendered text is parseable by
:func:`~app.agent.issue.parse_issue`, so a promoted candidate is *indistinguishable*
from a human-filed issue to everything downstream.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.models.entities import FindingSource
from app.runner.models import TraceFrame

# Relative severity weights used to rank candidates during triage.
SEVERITY_WEIGHT = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

_WS_RE = re.compile(r"\s+")


def _normalize_location(path: str, line: int | None) -> str:
    """A line-fuzzy location key: the path plus a coarse line bucket.

    Bucketing by 10 lines keeps the fingerprint stable across small edits above
    the bug site, so a re-scan after unrelated churn still dedups.
    """
    if not path:
        return ""
    bucket = "" if line is None else f":{line // 10 * 10}"
    return f"{path}{bucket}"


def fingerprint(*, rule: str, path: str, line: int | None, symbol: str) -> str:
    """A stable dedup key from rule id + normalized location + symbol.

    Two candidates with the same fingerprint are "the same bug" for refile
    purposes (§6). Stored on the ORM Finding with a unique-per-repo constraint,
    so a re-scan can never refile a known finding.
    """
    parts = [rule.strip(), _normalize_location(path, line), symbol.strip()]
    key = "|".join(_WS_RE.sub(" ", p) for p in parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


@dataclass
class Candidate:
    """A single latent-bug hypothesis emitted by a detector."""

    source: FindingSource
    summary: str
    rule: str  # detector rule id (e.g. ``pytest-fail``, ``mypy:union-attr``)
    evidence: str = ""  # untrusted: scanner output / stack trace, never executed
    path: str = ""
    line: int | None = None
    symbol: str = ""
    frames: list[TraceFrame] = field(default_factory=list)
    referenced_paths: list[str] = field(default_factory=list)
    confidence: float = 0.5
    severity: str = "medium"

    def fingerprint(self) -> str:
        return fingerprint(rule=self.rule, path=self.path, line=self.line, symbol=self.symbol)

    @property
    def rank_score(self) -> float:
        """confidence x severity — the triage ordering key (higher = fix first)."""
        return self.confidence * SEVERITY_WEIGHT.get(self.severity, 1.0)

    def render_issue(self) -> tuple[str, str]:
        """Render ``(title, body)`` as a synthetic issue the pipeline can parse.

        The body embeds the evidence and, when present, a native-style traceback
        block so :func:`~app.agent.issue.parse_issue` re-extracts the same frames
        a human-pasted stack trace would yield.
        """
        title = self.summary
        lines = [
            self.summary,
            "",
            f"Found by proactive discovery ({self.source.value} / `{self.rule}`).",
        ]
        if self.path:
            loc = self.path if self.line is None else f"{self.path}:{self.line}"
            lines += ["", f"Location: `{loc}`"]
        if self.symbol:
            lines.append(f"Symbol: `{self.symbol}`")
        if self.evidence.strip():
            lines += ["", "Evidence:", "", self.evidence.strip()]
        if self.frames:
            lines += ["", "Traceback (most recent call last):"]
            lines += [f'  File "{f.file}", line {f.line}, in {f.function}' for f in self.frames]
        return title, "\n".join(lines)
