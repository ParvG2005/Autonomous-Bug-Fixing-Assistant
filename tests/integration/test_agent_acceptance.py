"""Phase 3 acceptance: the agent turns a known-failing test green.

Hits the real Anthropic API (and runs tests in the local sandbox), so it is
marked ``integration`` and skips when ``ANTHROPIC_API_KEY`` is unset. This is the
Phase 3 acceptance behavior from the build plan: on a repo with a known failing
test, the agent produces a diff that turns it green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.client import make_create_message
from app.agent.loop import AgentLoop
from app.agent.models import AgentBudget
from app.agent.tools import ToolExecutor
from app.core.settings import get_settings
from app.index.repo_brain import RepoBrain
from app.sandbox import LocalSandbox, ResourceLimits

pytestmark = pytest.mark.integration


def test_agent_fixes_known_failing_test(agent_fixable: Path) -> None:
    settings = get_settings()
    if settings.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY not set")

    executor = ToolExecutor(
        agent_fixable,
        RepoBrain(agent_fixable),
        LocalSandbox(),
        limits=ResourceLimits(timeout_s=120.0),
    )
    loop = AgentLoop(
        executor,
        make_create_message(settings),
        model=settings.agent_model,
        budget=AgentBudget(max_iterations=12, deadline_s=300.0),
    )

    task = (
        "The test in test_mathutil.py fails: factorial(5) returns the wrong value. "
        "Find and fix the bug in mathutil.py so the test passes."
    )
    result = loop.run(task, verify_targets=["test_mathutil.py"])

    assert result.resolved, f"agent did not resolve: {result.stop_reason} / {result.summary}"
    assert result.diff, "expected a non-empty diff"
    assert result.edits, "expected at least one file edit"
    # The fix lands in the source, not the test.
    assert any(e.path == "mathutil.py" for e in result.edits)
