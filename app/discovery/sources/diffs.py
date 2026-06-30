"""Diff / hotspot signal (medium, deterministic).

Churn is a weak but cheap prior: source files changed often in recent history,
*without* an accompanying test, are likelier to harbor a latent regression. This
detector emits **low-confidence** candidates for such files — they rank last in
triage and most will fail to reproduce (and be dropped before any fix spend),
which is exactly the recall-oriented, precision-via-reproduction design.

Cut-order: diff-hunting is dropped second (after LLM review); it is the least
load-bearing source. Needs ``git`` in the sandbox image; absent → no candidates.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.discovery.finding import Candidate
from app.discovery.sources.base import ScanContext
from app.models.entities import FindingSource
from app.sandbox.models import ResourceLimits
from app.telemetry.logging import get_logger

log = get_logger("discovery.diffs")

_RECENT_COMMITS = 50
_MIN_CHURN = 2  # changed in at least this many recent commits to count as a hotspot


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}"


def _has_sibling_test(workspace: Path, path: str) -> bool:
    """True if a ``test_<stem>.py`` exists anywhere named after this module."""
    stem = Path(path).stem
    return any(workspace.rglob(f"test_{stem}.py")) or any(workspace.rglob(f"{stem}_test.py"))


class DiffHotspotDetector:
    """Recently-churned, untested source files → low-confidence candidates."""

    source = FindingSource.DIFF

    def detect(self, ctx: ScanContext) -> list[Candidate]:
        limits = ctx.limits or ResourceLimits()
        try:
            res = ctx.sandbox.run(
                ["git", "log", f"-n{_RECENT_COMMITS}", "--name-only", "--format="],
                ctx.workspace,
                limits,
            )
        except FileNotFoundError:
            return []
        if res.returncode != 0:
            return []

        churn: Counter[str] = Counter(
            line.strip()
            for line in res.stdout.splitlines()
            if line.strip().endswith(".py") and not _is_test(line.strip())
        )
        out: list[Candidate] = []
        for path, count in churn.most_common():
            if count < _MIN_CHURN or _has_sibling_test(ctx.workspace, path):
                continue
            if not (ctx.workspace / path).is_file():
                continue
            out.append(
                Candidate(
                    source=FindingSource.DIFF,
                    summary=f"Hotspot: `{path}` changed {count}x recently with no test",
                    rule="diff:untested-hotspot",
                    evidence=(
                        f"{path}: {count} changes in last {_RECENT_COMMITS} commits, "
                        "no sibling test"
                    ),
                    path=path,
                    confidence=0.15,
                    severity="low",
                )
            )
            if len(out) >= ctx.max_candidates:
                break
        log.info("diff_detector", emitted=len(out))
        return out
