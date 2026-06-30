"""Phase 4 acceptance: issue text → verified patch + reasoning writeup.

The core milestone from the build plan. Hits the real Anthropic API (tests run in
the local sandbox), so it is marked ``integration`` and skips without
``ANTHROPIC_API_KEY``.

Two scenarios:
* ``source_only_bug`` has a bug but **no test**, so the agent must *write a failing
  reproduction test* before fixing — exercising the Phase 4 reproduce deliverable.
* ``failing_project`` carries a traceback in the issue, exercising localization +
  node-id-scoped verification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.client import make_create_message
from app.agent.models import AgentBudget
from app.agent.solve import solve_issue
from app.core.settings import get_settings
from app.sandbox import LocalSandbox, ResourceLimits

pytestmark = pytest.mark.integration


def _solve(workspace: Path, issue: str):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if settings.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return solve_issue(
        workspace,
        issue,
        make_create_message(settings),
        model=settings.agent_model,
        sandbox=LocalSandbox(),
        budget=AgentBudget(max_iterations=16, deadline_s=360.0),
        limits=ResourceLimits(timeout_s=120.0),
    )


def test_solve_writes_reproduction_test_then_fixes(source_only_bug: Path) -> None:
    issue = (
        "titleize() is wrong\n\n"
        "Calling `titleize('hello world')` should return 'Hello World' "
        "(title case), but it returns 'HELLO WORLD'. There is no test for this yet."
    )
    result = _solve(source_only_bug, issue)

    assert result.resolved, f"unresolved: {result.agent.stop_reason} / {result.agent.summary}"
    # The fix landed in the source.
    assert any(e.path == "stringutil.py" for e in result.agent.edits)
    # A reproduction test was authored (a new test_*.py file).
    assert any("test" in e.path and e.path.endswith(".py") for e in result.agent.edits)
    # The writeup is a real Markdown report ending in a verdict.
    assert result.writeup.startswith("# ")
    assert "RESOLVED" in result.writeup
    assert (source_only_bug / "stringutil.py").read_text().count("title") >= 1


def test_solve_localizes_from_traceback(failing_project: Path) -> None:
    issue = (
        "divide by zero crashes\n\n"
        "`divide(1, 0)` raises instead of returning 0.\n\n"
        "Traceback (most recent call last):\n"
        '  File "calc.py", line 5, in divide\n'
        "    return a / b\n"
        "ZeroDivisionError: division by zero\n\n"
        "Repro: test_calc.py::test_divide_by_zero"
    )
    result = _solve(failing_project, issue)

    assert result.suspects[0].path == "calc.py"
    assert result.resolved, f"unresolved: {result.agent.stop_reason} / {result.agent.summary}"
    assert any(e.path == "calc.py" for e in result.agent.edits)
    assert "ZeroDivisionError" in result.writeup
