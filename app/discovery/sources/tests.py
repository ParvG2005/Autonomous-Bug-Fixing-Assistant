"""Existing-test signal (free, highest-confidence).

Run the repo's suite as-is. An already-failing or erroring test *is* a reproduced
bug — it skips discovery's noisy heuristics entirely and becomes a high-confidence
candidate with a real failing test and parsed frames already in hand.
"""

from __future__ import annotations

from app.discovery.finding import Candidate
from app.discovery.sources.base import ScanContext
from app.models.entities import FindingSource
from app.runner.models import TestFailure
from app.runner.run import NoTestFramework, run_tests
from app.telemetry.logging import get_logger

log = get_logger("discovery.tests")


class ExistingTestsDetector:
    """Promote currently-failing tests to high-confidence candidates."""

    source = FindingSource.TESTS

    def detect(self, ctx: ScanContext) -> list[Candidate]:
        try:
            result = run_tests(ctx.workspace, ctx.sandbox, limits=ctx.limits)
        except NoTestFramework:
            return []
        if result.ok:
            return []
        candidates = [self._to_candidate(f) for f in result.failures[: ctx.max_candidates]]
        log.info("tests_detector", failing=len(result.failures), emitted=len(candidates))
        return candidates

    def _to_candidate(self, failure: TestFailure) -> Candidate:
        innermost = failure.innermost_frame
        return Candidate(
            source=FindingSource.TESTS,
            summary=f"Failing test: {failure.nodeid}",
            rule="pytest-fail",
            evidence=f"{failure.nodeid}\n{failure.message}".strip(),
            path=innermost.file if innermost else failure.nodeid.split("::", 1)[0],
            line=innermost.line if innermost else None,
            symbol=innermost.function if innermost else "",
            frames=list(failure.frames),
            # A red test is the strongest signal we have — it is already reproduced.
            confidence=0.95,
            severity="high",
        )
