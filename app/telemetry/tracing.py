"""Agent tracing — the replayable record of a run, and its Langfuse mirror.

:func:`build_trace` distills a Phase-4 :class:`~app.agent.solve.SolveResult` into a
JSON-serializable dict capturing every tool call (name, arguments, result), the
plan, the localization, token usage, and the computed USD cost. Persisted as a
``TRACE`` artifact, it makes any past run reconstructable **offline** — no model
re-run, no Langfuse required (ARCHITECTURE.md §9, invariant "everything is
replayable"). Every string is run through the Phase-9 ``scrub`` filter so a secret
that surfaced in a tool result never lands in the trace.

A :class:`Tracer` optionally mirrors the trace to Langfuse and returns the
external trace id (stored on ``Run.langfuse_trace_id``). Offline / unconfigured,
:func:`get_tracer` returns a :class:`NullTracer` that records nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.core.settings import Settings
from app.telemetry.cost import cost_breakdown
from app.telemetry.logging import get_logger
from app.telemetry.redaction import scrub

if TYPE_CHECKING:
    from app.agent.solve import SolveResult

log = get_logger("telemetry.tracing")

# Tool results can be large (file dumps, test output); cap each in the trace.
_MAX_RESULT_CHARS = 8_000


def _scrub_value(value: Any) -> Any:
    """Recursively scrub strings inside JSON-ish values."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value


def build_trace(result: SolveResult, *, model: str) -> dict[str, Any]:
    """Build the replayable, secret-free trace dict for one solve run."""
    agent = result.agent
    return {
        "model": model,
        "resolved": agent.resolved,
        "stop_reason": agent.stop_reason.value,
        "iterations": agent.iterations,
        "plan": scrub(agent.plan),
        "summary": scrub(agent.summary),
        "flags": [scrub(f) for f in result.flags],
        "suspects": [
            {"path": s.path, "score": s.score, "reasons": [scrub(r) for r in s.reasons]}
            for s in result.suspects
        ],
        "tool_calls": [
            {
                "name": tc.name,
                "arguments": _scrub_value(tc.arguments),
                "result": scrub(tc.result[:_MAX_RESULT_CHARS]),
                "is_error": tc.is_error,
            }
            for tc in agent.tool_calls
        ],
        "edits": [{"path": e.path} for e in agent.edits],
        "usage": {
            "input_tokens": agent.usage.input_tokens,
            "output_tokens": agent.usage.output_tokens,
            "total_tokens": agent.usage.total,
        },
        "cost": cost_breakdown(model, agent.usage.input_tokens, agent.usage.output_tokens),
    }


@runtime_checkable
class Tracer(Protocol):
    """Emits a trace to an external sink and returns its id (or ``None``)."""

    def emit(self, trace: dict[str, Any], *, name: str) -> str | None: ...


class NullTracer:
    """No-op tracer — the offline / unconfigured default."""

    def emit(self, trace: dict[str, Any], *, name: str) -> str | None:
        return None


class LangfuseTracer:
    """Mirrors traces to Langfuse via the SDK (imported lazily)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def emit(self, trace: dict[str, Any], *, name: str) -> str | None:
        try:
            handle = self._client.trace(
                name=name,
                metadata=trace,
                input={"plan": trace.get("plan")},
                output={"summary": trace.get("summary"), "resolved": trace.get("resolved")},
            )
            return str(getattr(handle, "id", None) or "") or None
        except Exception as exc:  # never let telemetry break the pipeline
            log.warning("langfuse_emit_failed", error=str(exc))
            return None


def get_tracer(settings: Settings | None = None) -> Tracer:
    """Return a Langfuse tracer when configured + installed, else a NullTracer."""
    settings = settings or Settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return NullTracer()
    try:
        from langfuse import Langfuse
    except ImportError:
        log.warning("langfuse_not_installed")
        return NullTracer()
    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
    )
    return LangfuseTracer(client)
