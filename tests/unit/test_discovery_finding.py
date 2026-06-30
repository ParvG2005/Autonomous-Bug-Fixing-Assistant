"""Candidate fingerprinting + the render→parse round-trip (Phase 13)."""

from __future__ import annotations

from app.discovery.finding import Candidate, fingerprint
from app.discovery.promote import candidate_to_task
from app.models.entities import FindingSource
from app.runner.models import TraceFrame


def _cand(**kw: object) -> Candidate:
    base = dict(source=FindingSource.STATIC, summary="boom", rule="mypy:union-attr", path="a/b.py")
    base.update(kw)
    return Candidate(**base)  # type: ignore[arg-type]


def test_fingerprint_is_stable_and_line_fuzzy() -> None:
    # Same rule + symbol, lines in the same 10-line bucket → same fingerprint.
    a = fingerprint(rule="mypy:union-attr", path="a/b.py", line=12, symbol="f")
    b = fingerprint(rule="mypy:union-attr", path="a/b.py", line=15, symbol="f")
    assert a == b
    # A different rule or symbol → different fingerprint.
    assert a != fingerprint(rule="mypy:index", path="a/b.py", line=12, symbol="f")
    assert a != fingerprint(rule="mypy:union-attr", path="a/b.py", line=12, symbol="g")


def test_candidate_fingerprint_dedups_same_bug() -> None:
    assert _cand(line=10).fingerprint() == _cand(line=13).fingerprint()
    assert _cand(line=10).fingerprint() != _cand(line=99).fingerprint()


def test_rank_score_orders_by_confidence_times_severity() -> None:
    high = _cand(confidence=0.5, severity="high")
    low = _cand(confidence=0.5, severity="low")
    assert high.rank_score > low.rank_score


def test_render_issue_round_trips_through_parse_issue() -> None:
    cand = _cand(
        summary="None deref in handler",
        path="app/handler.py",
        line=42,
        symbol="handle",
        evidence="app/handler.py:42: error: Item 'None' has no attribute 'x'",
        frames=[TraceFrame(file="app/handler.py", line=42, function="handle")],
    )
    task = candidate_to_task(cand)
    assert task.title == "None deref in handler"
    # The embedded traceback survives the render→parse round-trip as frames.
    assert any(f.file == "app/handler.py" and f.line == 42 for f in task.frames)
