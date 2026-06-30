"""scan_repo fan-out: collects candidates, swallows detector errors (Phase 13)."""

from __future__ import annotations

from pathlib import Path

from app.discovery.finding import Candidate
from app.discovery.scan import scan_repo
from app.discovery.sources.base import ScanContext
from app.models.entities import FindingSource
from app.sandbox import LocalSandbox


class _ScriptedDetector:
    source = FindingSource.STATIC

    def __init__(self, candidates: list[Candidate]) -> None:
        self._candidates = candidates

    def detect(self, ctx: ScanContext) -> list[Candidate]:
        return list(self._candidates)


class _BoomDetector:
    source = FindingSource.DIFF

    def detect(self, ctx: ScanContext) -> list[Candidate]:
        raise RuntimeError("analyzer crashed")


def _cand(rule: str) -> Candidate:
    return Candidate(source=FindingSource.STATIC, summary=rule, rule=rule, path="x.py")


def test_scan_collects_candidates_from_all_detectors(tmp_path: Path) -> None:
    result = scan_repo(
        tmp_path,
        [_ScriptedDetector([_cand("a"), _cand("b")])],
        sandbox=LocalSandbox(),
    )
    assert {c.rule for c in result.candidates} == {"a", "b"}
    assert result.sources_run == ["static"]
    assert result.errors == {}


def test_scan_swallows_a_failing_detector(tmp_path: Path) -> None:
    result = scan_repo(
        tmp_path,
        [_BoomDetector(), _ScriptedDetector([_cand("ok")])],
        sandbox=LocalSandbox(),
    )
    # The crash is recorded but the other detector's candidates still come back.
    assert "diff" in result.errors
    assert {c.rule for c in result.candidates} == {"ok"}
