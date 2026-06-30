"""Aggregate fleet metrics: resolve rate, regression rate, time-to-fix, cost-per-fix."""

from __future__ import annotations

import pytest

from app.telemetry.metrics import JobOutcome, compute_metrics


def _outcome(
    *,
    resolved: bool,
    edited: bool = True,
    cost_usd: float = 1.0,
    duration_s: float = 60.0,
) -> JobOutcome:
    return JobOutcome(resolved=resolved, edited=edited, cost_usd=cost_usd, duration_s=duration_s)


def test_empty_set_is_all_zero() -> None:
    m = compute_metrics([])
    assert m.total == 0
    assert m.resolved == 0
    assert m.resolve_rate == 0.0
    assert m.regression_rate == 0.0
    assert m.mean_time_to_fix_s == 0.0
    assert m.cost_per_fix_usd == 0.0


def test_resolve_rate_is_resolved_over_total() -> None:
    m = compute_metrics([_outcome(resolved=True), _outcome(resolved=False)])
    assert m.total == 2
    assert m.resolved == 1
    assert m.resolve_rate == pytest.approx(0.5)


def test_regression_rate_is_unresolved_edits_over_edited() -> None:
    # Two jobs touched code: one fixed it, one didn't -> 50% left the tree changed-but-broken.
    # A third job made no edit, so it is not a regression candidate.
    outcomes = [
        _outcome(resolved=True, edited=True),
        _outcome(resolved=False, edited=True),
        _outcome(resolved=False, edited=False),
    ]
    m = compute_metrics(outcomes)
    assert m.regression_rate == pytest.approx(0.5)


def test_time_to_fix_averages_resolved_jobs_only() -> None:
    outcomes = [
        _outcome(resolved=True, duration_s=100.0),
        _outcome(resolved=True, duration_s=300.0),
        _outcome(resolved=False, duration_s=999.0),  # excluded
    ]
    m = compute_metrics(outcomes)
    assert m.mean_time_to_fix_s == pytest.approx(200.0)


def test_cost_per_fix_is_total_spend_over_resolved() -> None:
    outcomes = [
        _outcome(resolved=True, cost_usd=2.0),
        _outcome(resolved=False, cost_usd=4.0),  # spend counts, not a fix
    ]
    m = compute_metrics(outcomes)
    # total spend 6.0 across 1 fix
    assert m.cost_per_fix_usd == pytest.approx(6.0)


def test_cost_per_fix_zero_when_no_fixes() -> None:
    m = compute_metrics([_outcome(resolved=False, cost_usd=5.0)])
    assert m.cost_per_fix_usd == 0.0


def test_metrics_as_dict_is_json_friendly() -> None:
    m = compute_metrics([_outcome(resolved=True)])
    d = m.as_dict()
    assert d["total"] == 1
    assert d["resolve_rate"] == pytest.approx(1.0)
    assert set(d) >= {
        "total",
        "resolved",
        "resolve_rate",
        "regression_rate",
        "mean_time_to_fix_s",
        "cost_per_fix_usd",
        "total_cost_usd",
    }
