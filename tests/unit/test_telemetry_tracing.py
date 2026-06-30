"""Agent trace: a JSON-serializable, secret-free record that reconstructs a run."""

from __future__ import annotations

import json

from app.agent.localize import Suspect
from app.agent.models import (
    AgentResult,
    FileEdit,
    StopReason,
    TokenUsage,
    ToolCall,
)
from app.core.settings import Settings
from app.telemetry.tracing import NullTracer, build_trace, get_tracer


def _agent_result() -> AgentResult:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    return AgentResult(
        stop_reason=StopReason.RESOLVED,
        resolved=True,
        iterations=3,
        usage=usage,
        tool_calls=[
            ToolCall(name="read_file", arguments={"path": "calc.py"}, result="ok"),
            ToolCall(
                name="run_command",
                arguments={"cmd": "echo hi"},
                result="leaked ghp_0123456789abcdefghijklmnopqrstuvwxyz token",
                is_error=False,
            ),
        ],
        edits=[FileEdit(path="calc.py", before="a", after="b")],
        plan="reproduce then fix",
        summary="resolved: 1 passed",
    )


def _solve_result():  # type: ignore[no-untyped-def]
    from app.agent.solve import SolveResult
    from app.agent.writeup import ChangeSummary

    return SolveResult(
        task=None,  # type: ignore[arg-type]
        suspects=[Suspect(path="calc.py", score=2.0, reasons=["frame"])],
        agent=_agent_result(),
        flags=["sensitive:.github/x"],
        writeup="# writeup",
        summary=ChangeSummary(files_changed=["calc.py"], insertions=1, deletions=1),
    )


def test_build_trace_captures_every_tool_call() -> None:
    trace = build_trace(_solve_result(), model="claude-opus-4-8")
    assert len(trace["tool_calls"]) == 2
    assert trace["tool_calls"][0]["name"] == "read_file"
    assert trace["resolved"] is True
    assert trace["iterations"] == 3


def test_build_trace_reports_usage_and_cost() -> None:
    trace = build_trace(_solve_result(), model="claude-opus-4-8")
    assert trace["usage"]["total_tokens"] == 2_000_000
    # opus: 1M in @ $15 + 1M out @ $75 = $90
    assert trace["cost"]["cost_usd"] == 90.0


def test_build_trace_scrubs_secrets_from_tool_results() -> None:
    trace = build_trace(_solve_result(), model="claude-opus-4-8")
    blob = json.dumps(trace)
    assert "ghp_0123456789abcdefghijklmnopqrstuvwxyz" not in blob
    assert "***redacted***" in blob


def test_build_trace_is_json_serializable() -> None:
    # Must round-trip with no custom encoder (reconstructable from the artifact).
    json.loads(json.dumps(build_trace(_solve_result(), model="claude-opus-4-8")))


def test_null_tracer_emits_no_external_id() -> None:
    assert NullTracer().emit({"x": 1}, name="run") is None


def test_get_tracer_is_null_without_langfuse_keys() -> None:
    tracer = get_tracer(Settings(app_env="local"))
    assert isinstance(tracer, NullTracer)
