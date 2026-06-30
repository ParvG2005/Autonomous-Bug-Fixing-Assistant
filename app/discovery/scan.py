"""Fan detectors out over one cloned workspace and collect candidates.

:func:`scan_repo` is the in-sandbox orchestrator. It is deliberately DB-free and
synchronous (run it via ``asyncio.to_thread`` like ``solve_issue``): it takes a
materialized workspace + a sandbox + a detector list, runs each detector,
swallows per-detector failures (a crashing analyzer must not abort the scan), and
returns the raw candidates plus which sources actually ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.discovery.finding import Candidate
from app.discovery.sources.base import Detector, ScanContext
from app.sandbox.base import Sandbox
from app.sandbox.models import ResourceLimits
from app.telemetry.logging import get_logger

log = get_logger("discovery.scan")


@dataclass
class ScanResult:
    """The raw output of a scan, before triage."""

    candidates: list[Candidate] = field(default_factory=list)
    sources_run: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # source -> error message


def scan_repo(
    workspace: Path,
    detectors: list[Detector],
    *,
    sandbox: Sandbox,
    limits: ResourceLimits | None = None,
    max_candidates_per_detector: int = 50,
) -> ScanResult:
    """Run every detector over ``workspace`` and gather their candidates."""
    ctx = ScanContext(
        workspace=workspace,
        sandbox=sandbox,
        limits=limits,
        max_candidates=max_candidates_per_detector,
    )
    result = ScanResult()
    for detector in detectors:
        name = detector.source.value
        result.sources_run.append(name)
        try:
            found = detector.detect(ctx)
        except Exception as exc:  # one detector must never abort the whole scan
            log.error("detector_error", source=name, error=str(exc))
            result.errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        result.candidates.extend(found)
        log.info("detector_done", source=name, candidates=len(found))
    return result
