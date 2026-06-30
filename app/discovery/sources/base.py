"""The detector contract and the shared scan context.

A :class:`Detector` reads (and may execute, via the sandbox) untrusted repo code
and returns :class:`~app.discovery.finding.Candidate`s. It never creates jobs or
touches the DB — that is triage + promotion's job downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.discovery.finding import Candidate
from app.models.entities import FindingSource
from app.sandbox.base import Sandbox
from app.sandbox.models import ResourceLimits


@dataclass
class ScanContext:
    """Everything a detector needs to inspect one cloned workspace.

    ``sandbox`` is the same ephemeral, egress-off, capability-dropped sandbox the
    fix pipeline uses — detectors get no extra privilege (§7).
    """

    workspace: Path
    sandbox: Sandbox
    limits: ResourceLimits | None = None
    #: Cap on candidates a single detector may emit (recall-oriented but bounded).
    max_candidates: int = 50


@runtime_checkable
class Detector(Protocol):
    """One discovery signal. ``detect`` is recall-oriented and may be noisy —
    reproduction downstream enforces precision, so false positives are cheap."""

    source: FindingSource

    def detect(self, ctx: ScanContext) -> list[Candidate]:
        """Return candidate bugs found in ``ctx.workspace`` (possibly empty)."""
        ...
