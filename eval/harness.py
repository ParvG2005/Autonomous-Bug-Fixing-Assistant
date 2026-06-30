"""Run eval cases through the Phase 4 pipeline and record the per-case outcome.

:func:`run_case` materializes a case into a fresh workspace, runs
:func:`~app.agent.solve.solve_issue`, and distills the result into a
:class:`CaseResult` (resolved / edited / cost / duration). A case that *raises*
(clone failure, sandbox error, model error) becomes a non-resolved result with the
error recorded — one bad case never aborts the suite.

Everything is injected (model client, sandbox, clock), so the whole harness runs
offline against a scripted fake client + ``LocalSandbox``.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.agent.guardrails import DEFAULT_MAX_DIFF_LINES
from app.agent.loop import CreateMessage
from app.agent.models import AgentBudget
from app.agent.solve import solve_issue
from app.core.allowlist import Allowlist
from app.sandbox.base import Sandbox
from app.sandbox.models import ResourceLimits
from app.telemetry.cost import cost_usd
from eval.dataset import EvalCase

Clock = Callable[[], float]


@dataclass(frozen=True)
class CaseResult:
    """The outcome of running one :class:`~eval.dataset.EvalCase`."""

    case_id: str
    language: str
    resolved: bool
    edited: bool
    cost_usd: float
    duration_s: float
    stop_reason: str
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "language": self.language,
            "resolved": self.resolved,
            "edited": self.edited,
            "cost_usd": self.cost_usd,
            "duration_s": self.duration_s,
            "stop_reason": self.stop_reason,
            "error": self.error,
        }


@contextmanager
def _workspace_for(case: EvalCase, workspace_root: Path | None) -> Iterator[Path]:
    if workspace_root is not None:
        ws = workspace_root / case.id
        yield case.materialize(ws)
        return
    with tempfile.TemporaryDirectory(prefix=f"eval-{case.id}-") as tmp:
        yield case.materialize(Path(tmp))


def run_case(
    case: EvalCase,
    create_message: CreateMessage,
    *,
    model: str,
    sandbox: Sandbox | None = None,
    allowlist: Allowlist | None = None,
    budget: AgentBudget | None = None,
    limits: ResourceLimits | None = None,
    max_diff_lines: int = DEFAULT_MAX_DIFF_LINES,
    workspace_root: Path | None = None,
    clock: Clock = time.perf_counter,
) -> CaseResult:
    """Run one case end-to-end and return its :class:`CaseResult`.

    Any failure — materializing the workspace (e.g. a clone error), the sandbox,
    or the model — is caught and recorded as a non-resolved result so one bad case
    never aborts the suite.
    """
    start = clock()
    try:
        with _workspace_for(case, workspace_root) as ws:
            result = solve_issue(
                ws,
                case.issue_text,
                create_message,
                model=model,
                title=case.title,
                sandbox=sandbox,
                allowlist=allowlist,
                budget=budget,
                limits=limits,
                max_diff_lines=max_diff_lines,
            )
            duration = round(clock() - start, 3)
    except Exception as exc:
        return CaseResult(
            case_id=case.id,
            language=case.language,
            resolved=False,
            edited=False,
            cost_usd=0.0,
            duration_s=round(clock() - start, 3),
            stop_reason="error",
            error=f"{type(exc).__name__}: {exc}",
        )

    usage = result.agent.usage
    return CaseResult(
        case_id=case.id,
        language=case.language,
        resolved=result.resolved,
        edited=bool(result.agent.edits),
        cost_usd=cost_usd(model, usage.input_tokens, usage.output_tokens),
        duration_s=duration,
        stop_reason=str(result.agent.stop_reason),
        error=None,
    )


def run_suite(
    cases: list[EvalCase],
    create_message: CreateMessage,
    *,
    model: str,
    progress: Callable[[CaseResult], None] | None = None,
    **kwargs: object,
) -> list[CaseResult]:
    """Run every case sequentially, returning the per-case results.

    ``progress`` (if given) is called with each :class:`CaseResult` as it lands —
    the CLI uses it to stream a line per case. Cases run one at a time so the
    single shared sandbox / token budget stays predictable.
    """
    results: list[CaseResult] = []
    for case in cases:
        result = run_case(case, create_message, model=model, **kwargs)  # type: ignore[arg-type]
        if progress is not None:
            progress(result)
        results.append(result)
    return results
