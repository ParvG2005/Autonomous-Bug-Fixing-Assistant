"""Score a suite run and track score deltas across runs (the tuning loop).

Reuses :mod:`app.telemetry.metrics` so the eval's headline numbers are computed by
exactly the same code the live fleet reports. A :class:`CaseResult` carries the
four facts :class:`~app.telemetry.metrics.JobOutcome` needs, so scoring is a thin
map + :func:`~app.telemetry.metrics.compute_metrics`.

:func:`save_report` / :func:`load_report` persist a run to JSON, and
:func:`score_delta` diffs two runs' metrics — that is the "recorded score deltas"
the build plan asks for when tuning the retry budget, localization ranking, or
prompts: run, tweak, re-run, compare.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.telemetry.metrics import JobOutcome, Metrics, compute_metrics
from eval.harness import CaseResult


def to_outcomes(results: list[CaseResult]) -> list[JobOutcome]:
    """Map per-case results onto the metrics value object."""
    return [
        JobOutcome(
            resolved=r.resolved,
            edited=r.edited,
            cost_usd=r.cost_usd,
            duration_s=r.duration_s,
        )
        for r in results
    ]


@dataclass(frozen=True)
class EvalReport:
    """A scored suite run: headline metrics + the per-case breakdown."""

    suite: str
    model: str
    label: str
    metrics: Metrics
    cases: list[CaseResult]

    def headline(self) -> str:
        m = self.metrics
        return f"resolve rate {m.resolve_rate:.1%} ({m.resolved}/{m.total})"

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "model": self.model,
            "label": self.label,
            "metrics": self.metrics.as_dict(),
            "cases": [c.as_dict() for c in self.cases],
        }


def build_report(
    suite: str, model: str, results: list[CaseResult], *, label: str = ""
) -> EvalReport:
    """Score ``results`` into an :class:`EvalReport`."""
    return EvalReport(
        suite=suite,
        model=model,
        label=label,
        metrics=compute_metrics(to_outcomes(results)),
        cases=results,
    )


def save_report(report: EvalReport, path: Path) -> Path:
    """Persist ``report`` as JSON (parent dirs created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    return path


def load_report(path: Path) -> dict[str, Any]:
    """Load a previously-saved report's raw dict."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


# Headline metrics worth diffing across runs and whether higher is an improvement.
_DELTA_KEYS: dict[str, bool] = {
    "resolve_rate": True,
    "regression_rate": False,
    "cost_per_fix_usd": False,
    "mean_time_to_fix_s": False,
}


def score_delta(prev: Metrics | dict[str, Any], cur: Metrics) -> dict[str, dict[str, float]]:
    """Per-metric delta (cur - prev) plus whether it moved the right way.

    ``prev`` may be a :class:`Metrics` or the ``metrics`` dict from a saved report,
    so a stored baseline can be compared against a fresh run.
    """
    prev_d = prev.as_dict() if isinstance(prev, Metrics) else prev
    cur_d = cur.as_dict()
    out: dict[str, dict[str, float]] = {}
    for key, higher_better in _DELTA_KEYS.items():
        before = float(prev_d.get(key, 0.0))
        after = float(cur_d.get(key, 0.0))
        diff = round(after - before, 6)
        improved = diff >= 0 if higher_better else diff <= 0
        out[key] = {"before": before, "after": after, "delta": diff, "improved": float(improved)}
    return out
