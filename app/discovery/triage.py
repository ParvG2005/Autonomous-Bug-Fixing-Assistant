"""Rank, dedup, and budget-cap candidates into a promotable set.

Hunting a whole repo can spawn hundreds of candidates → token blowout. Triage is
the non-negotiable cost control (§6):

* **dedup** within the batch and against ``known_fingerprints`` (prior findings,
  open issues/PRs) — never refile what's known or in flight;
* **rank** by confidence x severity (the :attr:`Candidate.rank_score`);
* **budget cap** — at most ``max_jobs`` candidates are *promoted*; the rest are
  *parked* (stored as findings, not jobs).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.discovery.finding import Candidate


@dataclass
class TriageResult:
    """The triage verdict over a batch of candidates."""

    promote: list[Candidate] = field(default_factory=list)  # within budget → become jobs
    park: list[Candidate] = field(default_factory=list)  # over budget → stored, not promoted
    duplicates: list[Candidate] = field(default_factory=list)  # known/seen → dismissed

    @property
    def kept(self) -> list[Candidate]:
        """Promoted + parked, in rank order (everything that earned a Finding row)."""
        return self.promote + self.park


def triage(
    candidates: Iterable[Candidate],
    *,
    known_fingerprints: set[str] | None = None,
    max_jobs: int = 5,
) -> TriageResult:
    """Dedup, rank, and cap ``candidates`` into promote/park/duplicate buckets."""
    known = set(known_fingerprints or ())
    result = TriageResult()
    seen: set[str] = set()

    # Rank first so that, among duplicates, the highest-scoring representative is
    # the one kept; and so the budget cap promotes the best candidates.
    ranked = sorted(candidates, key=lambda c: c.rank_score, reverse=True)
    for cand in ranked:
        fp = cand.fingerprint()
        if fp in known or fp in seen:
            result.duplicates.append(cand)
            continue
        seen.add(fp)
        if len(result.promote) < max(0, max_jobs):
            result.promote.append(cand)
        else:
            result.park.append(cand)
    return result
