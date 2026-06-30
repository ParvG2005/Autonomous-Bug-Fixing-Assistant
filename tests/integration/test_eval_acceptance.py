"""Phase 11 acceptance: one command runs the eval and prints a headline resolve rate.

Hits the real Anthropic API (tests run in the local sandbox), so it is marked
``integration`` and skips without ``ANTHROPIC_API_KEY``. Runs the shipped custom
suite end-to-end and asserts a real headline number comes out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval.dataset import load_suite
from eval.harness import run_suite
from eval.score import build_report

from app.agent.client import make_create_message
from app.agent.models import AgentBudget
from app.core.settings import get_settings
from app.sandbox import LocalSandbox, ResourceLimits

pytestmark = pytest.mark.integration


def test_custom_suite_runs_and_scores(tmp_path: Path) -> None:
    settings = get_settings()
    if settings.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY not set")

    cases = load_suite("custom")
    results = run_suite(
        cases,
        make_create_message(settings),
        model=settings.agent_model,
        sandbox=LocalSandbox(),
        budget=AgentBudget(max_iterations=16, deadline_s=360.0),
        limits=ResourceLimits(timeout_s=120.0),
        workspace_root=tmp_path,
    )
    report = build_report("custom", settings.agent_model, results)

    # A real headline number is produced over every case.
    assert report.metrics.total == len(cases)
    assert "resolve rate" in report.headline()
    # The harness is sound: these are known-fixable bugs, so we expect a strong
    # resolve rate (allowing one miss to absorb model nondeterminism).
    assert report.metrics.resolved >= len(cases) - 1
