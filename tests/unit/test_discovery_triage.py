"""Triage: dedup, rank, and budget-cap (Phase 13 §6)."""

from __future__ import annotations

from app.discovery.finding import Candidate
from app.discovery.triage import triage
from app.models.entities import FindingSource


def _cand(rule: str, *, conf: float = 0.5, sev: str = "medium", path: str = "x.py") -> Candidate:
    return Candidate(
        source=FindingSource.STATIC,
        summary=rule,
        rule=rule,
        path=path,
        confidence=conf,
        severity=sev,
    )


def test_dedup_within_batch_and_against_known() -> None:
    dup_a = _cand("r1")
    dup_b = _cand("r1")  # same fingerprint as dup_a
    fresh = _cand("r2")
    result = triage([dup_a, dup_b, fresh], max_jobs=10)
    assert len(result.duplicates) == 1  # the second r1 is a dupe
    assert {c.rule for c in result.kept} == {"r1", "r2"}

    # A known fingerprint is dropped entirely (the re-scan guarantee).
    again = triage([_cand("r2")], known_fingerprints={_cand("r2").fingerprint()})
    assert again.promote == [] and len(again.duplicates) == 1


def test_budget_cap_promotes_best_first_and_parks_rest() -> None:
    cands = [
        _cand("low", conf=0.2, sev="low"),
        _cand("crit", conf=0.9, sev="critical"),
        _cand("mid", conf=0.5, sev="medium"),
    ]
    result = triage(cands, max_jobs=1)
    assert [c.rule for c in result.promote] == ["crit"]  # highest score promoted
    assert {c.rule for c in result.park} == {"low", "mid"}  # rest parked, not jobs


def test_zero_budget_parks_everything() -> None:
    result = triage([_cand("a"), _cand("b")], max_jobs=0)
    assert result.promote == []
    assert len(result.park) == 2
