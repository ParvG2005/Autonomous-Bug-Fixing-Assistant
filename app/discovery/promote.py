"""Candidate → synthetic IssueTask (the seam to the existing flow, §5).

:func:`candidate_to_task` renders a candidate to issue text and parses it back
into the **same** :class:`~app.agent.issue.IssueTask` ``parse_issue`` produces for
a human-filed issue — so a promoted candidate is indistinguishable downstream.
The round-trip (render → parse) is intentional: it guarantees the frames the
pipeline localizes from are exactly what a maintainer pasting the same evidence
would get, with no second code path to keep in sync.

DB-side promotion (persisting the Finding + enqueuing the job) lives in
:mod:`app.db.discovery`; this module is the pure conversion.
"""

from __future__ import annotations

from app.agent.issue import IssueTask, parse_issue
from app.discovery.finding import Candidate
from app.models.entities import Finding
from app.runner.models import TraceFrame


def candidate_to_task(candidate: Candidate) -> IssueTask:
    """Render ``candidate`` to issue text and parse it into an :class:`IssueTask`."""
    title, body = candidate.render_issue()
    return parse_issue(body, title=title)


def finding_to_candidate(finding: Finding) -> Candidate:
    """Reconstruct an in-memory candidate from a persisted FINDING row.

    Used when a human promotes a *parked* finding from the dashboard: the row
    carries everything render needs, so promotion reuses the same issue rendering
    as a fresh candidate.
    """
    frames = [
        TraceFrame(
            file=str(f.get("file", "")),
            line=int(f.get("line", 0)),
            function=str(f.get("function", "")),
        )
        for f in (finding.frames or [])
    ]
    fr = frames[-1] if frames else None
    return Candidate(
        source=finding.source,
        summary=finding.summary,
        rule=finding.fingerprint,  # exact fingerprint preserved (already deduped)
        evidence=finding.evidence,
        path=fr.file if fr else "",
        line=fr.line if fr else None,
        symbol=fr.function if fr else "",
        frames=frames,
        confidence=finding.confidence,
        severity=finding.severity,
    )
