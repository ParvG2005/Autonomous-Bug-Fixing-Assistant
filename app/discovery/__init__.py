"""Proactive bug discovery (Phase 13).

Turns a repo into a *job source*: detectors hunt for latent bugs and emit cheap,
noisy :class:`~app.discovery.finding.Candidate`s; triage dedups and budget-caps
them; promotion converts a survivor into the **same synthetic issue** the webhook
produces, so everything downstream (reproduce → fix → verify → human-gated draft
PR) is the existing pipeline, unchanged. Reproduction — not the finder — is the
precision filter: a candidate that won't go red is dropped before any fix spend.
"""

from __future__ import annotations

from app.discovery.finding import Candidate, fingerprint
from app.discovery.scan import ScanResult, scan_repo
from app.discovery.triage import TriageResult, triage

__all__ = [
    "Candidate",
    "ScanResult",
    "TriageResult",
    "fingerprint",
    "scan_repo",
    "triage",
]
