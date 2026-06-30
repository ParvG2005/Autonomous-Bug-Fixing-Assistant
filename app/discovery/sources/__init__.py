"""Discovery detectors (Phase 13).

Each detector is one tiered signal (cheap → expensive): existing test failures,
static analysis, runtime evidence, diff/hotspots, LLM review. They share the
:class:`~app.discovery.sources.base.Detector` protocol and a
:class:`~app.discovery.sources.base.ScanContext`, and all run inside the same
ephemeral sandbox as the rest of the system — no new trust boundary (§7).

Cut-order: the LLM-review source is dropped first, then diff-hunting; the
deterministic test + static sources alone are a useful, cheap product. Runtime
evidence (Sentry/Datadog) is a thin connector left as a future addition.
"""

from __future__ import annotations

from app.discovery.sources.base import Detector, ScanContext
from app.discovery.sources.diffs import DiffHotspotDetector
from app.discovery.sources.static import StaticAnalysisDetector
from app.discovery.sources.tests import ExistingTestsDetector

#: The default detector set, cheap → expensive. Runtime/review are opt-in.
DEFAULT_DETECTORS: list[Detector] = [
    ExistingTestsDetector(),
    StaticAnalysisDetector(),
    DiffHotspotDetector(),
]

__all__ = [
    "DEFAULT_DETECTORS",
    "Detector",
    "DiffHotspotDetector",
    "ExistingTestsDetector",
    "ScanContext",
    "StaticAnalysisDetector",
]
