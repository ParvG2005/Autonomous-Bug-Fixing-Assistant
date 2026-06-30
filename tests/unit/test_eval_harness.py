"""Offline test of the eval harness: scripted fake client + real LocalSandbox.

Reuses the Phase 4 scripted-client pattern — the fix and its verification are
genuine; only the model is faked. Proves a case runs end-to-end into a scored
CaseResult, that the clock is injected (deterministic duration), and that a
raising case degrades to a recorded error instead of aborting the suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.dataset import EvalCase, load_suite
from eval.harness import CaseResult, run_case, run_suite

from app.agent.models import AgentBudget
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
    input_tokens: int = 1000
    output_tokens: int = 500


@dataclass
class _Response:
    content: list[Any]
    stop_reason: str
    usage: _Usage = field(default_factory=_Usage)


class _ScriptedClient:
    def __init__(self, responses: list[_Response]) -> None:
        self._responses = list(responses)

    def create(self, **kwargs: Any) -> _Response:
        return self._responses.pop(0)


def _divide_case() -> EvalCase:
    return next(c for c in load_suite("custom") if c.id == "02-divide-by-zero")


def _divide_fix_client() -> _ScriptedClient:
    return _ScriptedClient(
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
            _Response([_Text("Guarded divide().")], "end_turn"),
        ]
    )


def test_run_case_resolves_and_scores(tmp_path: Path) -> None:
    ticks = iter([100.0, 137.5])  # start, end -> 37.5s
    result = run_case(
        _divide_case(),
        _divide_fix_client().create,
        model="claude-opus-4-8",
        sandbox=LocalSandbox(),
        budget=AgentBudget(max_iterations=5, deadline_s=120.0),
        limits=ResourceLimits(timeout_s=60.0),
        workspace_root=tmp_path,
        clock=lambda: next(ticks),
    )
    assert isinstance(result, CaseResult)
    assert result.case_id == "02-divide-by-zero"
    assert result.resolved is True
    assert result.edited is True
    assert result.duration_s == 37.5
    assert result.cost_usd > 0.0  # opus is in the price table
    assert result.error is None


def test_run_case_records_error_instead_of_raising(tmp_path: Path) -> None:
    def _boom(_dest: Path) -> None:
        raise RuntimeError("clone failed")

    case = EvalCase(id="broken", issue_text="x", setup=_boom)
    result = run_case(
        case,
        _ScriptedClient([]).create,
        model="claude-opus-4-8",
        sandbox=LocalSandbox(),
        workspace_root=tmp_path,
        clock=lambda: 0.0,
    )
    assert result.resolved is False
    assert result.edited is False
    assert result.cost_usd == 0.0
    assert result.error is not None
    assert "clone failed" in result.error


def test_run_suite_streams_progress(tmp_path: Path) -> None:
    seen: list[str] = []
    results = run_suite(
        [_divide_case()],
        _divide_fix_client().create,
        model="claude-opus-4-8",
        progress=lambda r: seen.append(r.case_id),
        sandbox=LocalSandbox(),
        budget=AgentBudget(max_iterations=5, deadline_s=120.0),
        limits=ResourceLimits(timeout_s=60.0),
        workspace_root=tmp_path,
    )
    assert seen == ["02-divide-by-zero"]
    assert len(results) == 1 and results[0].resolved
