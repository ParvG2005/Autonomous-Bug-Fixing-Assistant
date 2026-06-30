"""Fleet metrics — resolve rate, regression rate, time-to-fix, cost-per-fix.

Pure aggregation over :class:`JobOutcome` value objects so the math is unit-
testable without a database. The API layer maps ORM rows (job state + fix +
cost + timestamps) into :class:`JobOutcome` and calls :func:`compute_metrics`.

Definitions:

- **resolve_rate** = resolved jobs / total jobs. "Resolved" means the fix's
  authoritative verification passed.
- **regression_rate** = jobs that edited code but did *not* resolve / jobs that
  edited code. A defensible proxy: the agent changed the tree but left it broken
  or unfixed (no post-merge signal exists offline).
- **mean_time_to_fix_s** = mean wall-clock duration over resolved jobs only.
- **cost_per_fix_usd** = total token spend (all jobs) / number of resolved fixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobOutcome:
    """The few facts about one finished job that the metrics need."""

    resolved: bool
    edited: bool
    cost_usd: float
    duration_s: float


@dataclass(frozen=True)
class Metrics:
    """Aggregate metrics over a set of jobs."""

    total: int
    resolved: int
    resolve_rate: float
    regression_rate: float
    mean_time_to_fix_s: float
    cost_per_fix_usd: float
    total_cost_usd: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "resolved": self.resolved,
            "resolve_rate": self.resolve_rate,
            "regression_rate": self.regression_rate,
            "mean_time_to_fix_s": self.mean_time_to_fix_s,
            "cost_per_fix_usd": self.cost_per_fix_usd,
            "total_cost_usd": self.total_cost_usd,
        }


def compute_metrics(outcomes: list[JobOutcome]) -> Metrics:
    """Aggregate ``outcomes`` into the headline metrics (empty set -> all zero)."""
    total = len(outcomes)
    resolved = [o for o in outcomes if o.resolved]
    n_resolved = len(resolved)

    edited = [o for o in outcomes if o.edited]
    regressions = [o for o in edited if not o.resolved]

    total_cost = round(sum(o.cost_usd for o in outcomes), 6)

    return Metrics(
        total=total,
        resolved=n_resolved,
        resolve_rate=(n_resolved / total) if total else 0.0,
        regression_rate=(len(regressions) / len(edited)) if edited else 0.0,
        mean_time_to_fix_s=(
            sum(o.duration_s for o in resolved) / n_resolved if n_resolved else 0.0
        ),
        cost_per_fix_usd=(total_cost / n_resolved) if n_resolved else 0.0,
        total_cost_usd=total_cost,
    )
