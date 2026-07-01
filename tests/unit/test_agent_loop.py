"""Loop tests with a scripted fake Anthropic client (offline).

The fake returns a pre-baked sequence of responses, so we exercise the full loop
— planning step, tool dispatch, edit application, stop-reason handling, and the
authoritative final verification — without the network. Verification runs the
real LocalSandbox against the fixture, so a green result is genuine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.loop import AgentLoop
from app.agent.models import AgentBudget, StopReason
from app.agent.tools import ToolExecutor
from app.index.repo_brain import RepoBrain
from app.sandbox import LocalSandbox, ResourceLimits


@dataclass
class _Text:
    text: str
    type: str = "text"


@dataclass
class _ToolUse:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class _Response:
    content: list[Any]
    stop_reason: str
    usage: _Usage = field(default_factory=_Usage)


class _ScriptedClient:
    """Pops queued responses; records each request for assertions."""

    def __init__(self, responses: list[_Response]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _loop(root: Path, client: _ScriptedClient) -> AgentLoop:
    executor = ToolExecutor(
        root, RepoBrain(root), LocalSandbox(), limits=ResourceLimits(timeout_s=60.0)
    )
    return AgentLoop(
        executor,
        client.create,
        model="claude-opus-4-8",
        budget=AgentBudget(max_iterations=10, deadline_s=120.0),
    )


def test_loop_fixes_bug_and_verifies(agent_fixable: Path) -> None:
    client = _ScriptedClient(
        [
            _Response([_Text("Plan: read, fix the range, run tests.")], "end_turn"),
            _Response(
                [
                    _ToolUse(
                        "t1",
                        "edit_file",
                        {
                            "path": "mathutil.py",
                            "old_str": "for i in range(1, n):",
                            "new_str": "for i in range(1, n + 1):",
                        },
                    )
                ],
                "tool_use",
            ),
            _Response([_Text("Fixed the off-by-one in factorial.")], "end_turn"),
        ]
    )
    loop = _loop(agent_fixable, client)

    result = loop.run("factorial(5) should be 120 but the test fails.")

    assert result.resolved is True
    assert result.stop_reason is StopReason.RESOLVED
    assert result.plan.startswith("Plan:")
    assert len(result.edits) == 1
    assert "n + 1" in result.diff
    assert "range(1, n + 1)" in (agent_fixable / "mathutil.py").read_text()
    # planning call + working turns
    assert len(client.calls) == 3
    # planning call carries no tools; working calls do
    assert "tools" not in client.calls[0]
    assert "tools" in client.calls[1]


def test_loop_reports_unresolved_when_no_fix(agent_fixable: Path) -> None:
    client = _ScriptedClient(
        [
            _Response([_Text("plan")], "end_turn"),
            _Response([_Text("I give up.")], "end_turn"),
        ]
    )
    loop = _loop(agent_fixable, client)

    result = loop.run("fix it", do_plan=True)

    assert result.resolved is False
    assert result.stop_reason is StopReason.COMPLETED
    assert result.edits == []


def test_loop_respects_iteration_budget(agent_fixable: Path) -> None:
    # Always ask for a (harmless) tool call so the loop never ends on its own.
    responses = [_Response([_Text("plan")], "end_turn")] + [
        _Response([_ToolUse(f"t{i}", "read_file", {"path": "mathutil.py"})], "tool_use")
        for i in range(10)
    ]
    client = _ScriptedClient(responses)
    executor = ToolExecutor(
        agent_fixable,
        RepoBrain(agent_fixable),
        LocalSandbox(),
        limits=ResourceLimits(timeout_s=60.0),
    )
    loop = AgentLoop(
        executor,
        client.create,
        model="claude-opus-4-8",
        budget=AgentBudget(max_iterations=3, deadline_s=120.0),
    )

    result = loop.run("fix it", do_plan=True)

    assert result.iterations == 3
    assert result.resolved is False
    assert result.stop_reason is StopReason.MAX_ITERATIONS


def test_loop_aborts_early_when_repro_uncollectable(tmp_path: Path) -> None:
    # The repo's test can't even be imported (missing module) — there is no
    # failing-test signal to iterate against. The loop must abort BEFORE spending
    # any model calls, rather than flailing to max_iterations.
    (tmp_path / "test_thing.py").write_text(
        "import nonexistent_pkg_xyz\n\n\ndef test_x():\n    assert nonexistent_pkg_xyz.f() == 1\n",
        encoding="utf-8",
    )
    client = _ScriptedClient([])  # must not be called
    loop = _loop(tmp_path, client)

    result = loop.run("fix the bug")

    assert result.stop_reason is StopReason.UNREPRODUCIBLE
    assert result.resolved is False
    assert result.iterations == 0
    assert result.edits == []
    assert client.calls == []  # aborted before planning/any model call
    assert "nonexistent_pkg_xyz" in result.summary


def test_loop_token_accounting(agent_fixable: Path) -> None:
    client = _ScriptedClient(
        [
            _Response([_Text("plan")], "end_turn"),
            _Response([_Text("done")], "end_turn"),
        ]
    )
    loop = _loop(agent_fixable, client)
    result = loop.run("fix it")
    # Planning turn (150) + one working turn (150) both count toward the budget.
    assert result.usage.total == 300
