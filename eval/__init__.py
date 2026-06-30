"""Phase 11 eval harness.

Turns the Phase 4 :func:`~app.agent.solve.solve_issue` pipeline into a measurable
benchmark: a *suite* of buggy-commit cases, each run end-to-end, scored with the
same :mod:`app.telemetry.metrics` the fleet uses (resolve rate, regression rate,
cost-per-fix). One command (``bugfix-eval run``) prints the headline resolve rate.

Two dataset sources:

* **custom** — a small set of buggy Python projects shipped in ``eval/data/custom``;
  the offline-tested core (a scripted fake client + ``LocalSandbox`` exercises the
  whole harness without the network).
* **swebench-lite** — a loader (:mod:`eval.swebench`) for the SWE-bench-lite
  instances; materializing a case clones the real repo at its base commit, so it is
  gated behind the network/dataset just like the Phase 5/8 acceptance tests.

Running the harness against the real model **costs tokens** — the build plan lists
it as a stop-and-ask gate, so :mod:`eval.cli` refuses a real run without
``--confirm``.
"""

from __future__ import annotations

from eval.dataset import CUSTOM_SUITE, EvalCase, load_suite
from eval.harness import CaseResult, run_case, run_suite
from eval.score import EvalReport, build_report, score_delta, to_outcomes

__all__ = [
    "CUSTOM_SUITE",
    "CaseResult",
    "EvalCase",
    "EvalReport",
    "build_report",
    "load_suite",
    "run_case",
    "run_suite",
    "score_delta",
    "to_outcomes",
]
