"""Value types produced and consumed by the agent loop.

The loop turns a task (e.g. "make this failing test green") into a sequence of
tool calls and, on success, a unified diff. These types capture the budget that
bounds the loop, a record of every tool call, and the structured result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class StopReason(StrEnum):
    """Why the agent loop stopped."""

    COMPLETED = "completed"  # model ended its turn (no more tool calls)
    RESOLVED = "resolved"  # target tests pass (early stop)
    MAX_ITERATIONS = "max_iterations"
    TOKEN_BUDGET = "token_budget"
    TIME_BUDGET = "time_budget"
    REFUSED = "refused"  # model returned stop_reason="refusal"
    ERROR = "error"  # an unrecoverable error in the loop


@dataclass(frozen=True)
class AgentBudget:
    """Ceilings that bound a single agent run.

    Defaults are conservative for a single-bug fix. ``max_iterations`` caps the
    number of model turns (each turn may issue several tool calls);
    ``max_tokens`` caps cumulative input+output tokens across the run;
    ``deadline_s`` is the wall-clock budget.
    """

    max_iterations: int = 20
    max_tokens: int = 400_000
    deadline_s: float = 600.0


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation and its result, for the trace."""

    name: str
    arguments: dict[str, object]
    result: str
    is_error: bool = False


@dataclass(frozen=True)
class FileEdit:
    """One applied edit: the before/after text of a workspace file."""

    path: str
    before: str
    after: str


@dataclass
class TokenUsage:
    """Cumulative token accounting across a run."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


@dataclass
class AgentResult:
    """Structured outcome of an agent run."""

    stop_reason: StopReason
    resolved: bool
    iterations: int
    usage: TokenUsage
    tool_calls: list[ToolCall] = field(default_factory=list)
    edits: list[FileEdit] = field(default_factory=list)
    diff: str = ""
    plan: str = ""
    summary: str = ""
