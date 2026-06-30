"""Offline test of the Phase 4 orchestrator: issue -> reproduce/localize/fix -> writeup.

Uses a scripted fake Anthropic client and the real LocalSandbox/RepoBrain, so the
fix and its verification are genuine — only the model is faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.models import AgentBudget
from app.agent.solve import solve_issue
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
    def __init__(self, responses: list[_Response]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        return self._responses.pop(0)


_ISSUE = """\
divide by zero crashes

`divide(1, 0)` raises instead of returning 0.

Traceback (most recent call last):
  File "calc.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero

Repro test: test_calc.py::test_divide_by_zero
"""


def test_solve_issue_localizes_fixes_and_writes_up(failing_project: Path) -> None:
    client = _ScriptedClient(
        [
            _Response([_Text("Plan: guard divide against a zero denominator.")], "end_turn"),
            _Response(
                [
                    _ToolUse(
                        "t1",
                        "edit_file",
                        {
                            "path": "calc.py",
                            "old_str": "def divide(a, b):\n    return a / b",
                            "new_str": (
                                "def divide(a, b):\n    if b == 0:\n        return 0\n"
                                "    return a / b"
                            ),
                        },
                    )
                ],
                "tool_use",
            ),
            _Response([_Text("Guarded divide() against a zero denominator.")], "end_turn"),
        ]
    )

    result = solve_issue(
        failing_project,
        _ISSUE,
        client.create,
        model="claude-opus-4-8",
        sandbox=LocalSandbox(),
        budget=AgentBudget(max_iterations=5, deadline_s=120.0),
        limits=ResourceLimits(timeout_s=60.0),
    )

    # Localization put calc.py at the top from the traceback.
    assert result.suspects[0].path == "calc.py"
    # The node id in the issue scoped the authoritative verification.
    assert result.task.test_nodeids == ["test_calc.py::test_divide_by_zero"]
    assert result.agent.resolved is True
    # Change summary + writeup reflect the real fix.
    assert result.summary.files_changed == ["calc.py"]
    assert "RESOLVED" in result.writeup
    assert "calc.py" in result.writeup
    assert "ZeroDivisionError" in result.writeup
    assert result.flags == []
