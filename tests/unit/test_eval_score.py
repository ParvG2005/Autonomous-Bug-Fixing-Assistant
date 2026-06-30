"""Offline tests for eval scoring + score deltas (the tuning loop)."""

from __future__ import annotations

from pathlib import Path

from eval.harness import CaseResult
from eval.score import build_report, load_report, save_report, score_delta, to_outcomes

from app.telemetry.metrics import compute_metrics


def _result(case_id: str, *, resolved: bool, edited: bool = True, cost: float = 0.01) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        language="python",
        resolved=resolved,
        edited=edited,
        cost_usd=cost,
        duration_s=10.0,
        stop_reason="resolved" if resolved else "exhausted",
    )


def test_build_report_reuses_fleet_metrics() -> None:
    results = [_result("a", resolved=True), _result("b", resolved=False)]
    report = build_report("custom", "claude-opus-4-8", results, label="baseline")
    # The report's metrics must match computing them directly from outcomes.
    assert report.metrics == compute_metrics(to_outcomes(results))
    assert report.metrics.resolve_rate == 0.5
    assert report.headline() == "resolve rate 50.0% (1/2)"


def test_save_and_load_report_roundtrip(tmp_path: Path) -> None:
    report = build_report("custom", "m", [_result("a", resolved=True)], label="run1")
    path = save_report(report, tmp_path / "r" / "run1.json")
    loaded = load_report(path)
    assert loaded["suite"] == "custom"
    assert loaded["label"] == "run1"
    assert loaded["metrics"]["resolve_rate"] == 1.0
    assert loaded["cases"][0]["case_id"] == "a"


def test_score_delta_flags_improvement_and_regression() -> None:
    prev = build_report("custom", "m", [_result("a", resolved=False)]).metrics
    cur = build_report("custom", "m", [_result("a", resolved=True)]).metrics
    delta = score_delta(prev, cur)
    # resolve_rate went 0 -> 1: improved.
    assert delta["resolve_rate"]["delta"] == 1.0
    assert delta["resolve_rate"]["improved"] == 1.0
    # regression_rate: edited-but-unresolved went 1.0 -> 0.0: lower is better -> improved.
    assert delta["regression_rate"]["improved"] == 1.0


def test_score_delta_accepts_saved_metrics_dict() -> None:
    cur = build_report("custom", "m", [_result("a", resolved=True)]).metrics
    prev_dict = {
        "resolve_rate": 0.5,
        "regression_rate": 0.0,
        "cost_per_fix_usd": 0.0,
        "mean_time_to_fix_s": 0.0,
    }
    delta = score_delta(prev_dict, cur)
    assert delta["resolve_rate"]["before"] == 0.5
    assert delta["resolve_rate"]["after"] == 1.0
