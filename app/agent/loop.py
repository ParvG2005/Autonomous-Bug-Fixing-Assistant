"""The core agent loop: an Anthropic tool-use loop bounded by a budget.

``AgentLoop`` drives a manual tool-use loop (we control it, rather than the SDK
runner, so the allowlist gates every dispatch and the retry/token/time budget is
enforced turn by turn). It optionally runs a planning step first, then loops:
ask the model, execute any tool calls it requests, feed results back, repeat —
until the model ends its turn, the target tests pass, or a budget ceiling trips.

The model client is injected as a ``create_message`` callable (the production
wiring passes ``anthropic.Anthropic().messages.create``), which keeps the loop
testable offline with a scripted fake.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.agent.models import (
    AgentBudget,
    AgentResult,
    StopReason,
    TokenUsage,
)
from app.agent.prompts import PLANNING_PROMPT, SYSTEM_PROMPT, build_task_prompt
from app.agent.tools import ToolExecutor, tool_schemas

# A callable with the shape of ``anthropic.Anthropic().messages.create``.
CreateMessage = Callable[..., Any]


class AgentLoop:
    """Runs the tool-use loop for one workspace within a budget."""

    def __init__(
        self,
        executor: ToolExecutor,
        create_message: CreateMessage,
        *,
        model: str,
        budget: AgentBudget | None = None,
        max_tokens: int = 16_000,
        effort: str = "high",
    ) -> None:
        self.executor = executor
        self.create_message = create_message
        self.model = model
        self.budget = budget or AgentBudget()
        self.max_tokens = max_tokens
        self.effort = effort

    def _create(self, messages: list[dict[str, Any]], *, tools: bool) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
        }
        if tools:
            kwargs["tools"] = tool_schemas()
        return self.create_message(**kwargs)

    def plan(self, task: str, usage: TokenUsage | None = None) -> str:
        """Run the planning step: one toolless turn that returns a text plan.

        Planning tokens count toward the budget when ``usage`` is supplied.
        """
        messages = [{"role": "user", "content": f"Task:\n{task}\n\n{PLANNING_PROMPT}"}]
        response = self._create(messages, tools=False)
        if usage is not None:
            _accumulate_usage(usage, response)
        return _text_of(response)

    def run(
        self,
        task: str,
        *,
        verify_targets: list[str] | None = None,
        do_plan: bool = True,
    ) -> AgentResult:
        """Diagnose and fix the bug described by ``task``.

        ``verify_targets`` restricts the final, authoritative test run used to
        decide ``resolved`` (defaults to the whole suite). The loop runs that
        verification itself rather than trusting the model's last run.
        """
        usage = TokenUsage()
        deadline = time.monotonic() + self.budget.deadline_s

        plan = self.plan(task, usage) if do_plan else ""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": build_task_prompt(task, plan)}
        ]

        stop = StopReason.MAX_ITERATIONS
        summary = ""
        iterations = 0

        while iterations < self.budget.max_iterations:
            if time.monotonic() >= deadline:
                stop = StopReason.TIME_BUDGET
                break
            if usage.total >= self.budget.max_tokens:
                stop = StopReason.TOKEN_BUDGET
                break

            iterations += 1
            response = self._create(messages, tools=True)
            _accumulate_usage(usage, response)
            messages.append({"role": "assistant", "content": response.content})

            reason = getattr(response, "stop_reason", None)
            if reason == "refusal":
                stop = StopReason.REFUSED
                summary = _text_of(response)
                break
            if reason == "pause_turn":
                # Server-side pause: re-send to let the model resume.
                continue
            if reason != "tool_use":
                stop = StopReason.COMPLETED
                summary = _text_of(response)
                break

            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result_text, is_error = self.executor.dispatch(block.name, dict(block.input))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

            # Early stop: the model's own run shows the suite green and we've edited.
            last = self.executor.last_test_result
            if last is not None and last.ok and self.executor.edits:
                stop = StopReason.RESOLVED
                break

        resolved, final_summary = self._verify(verify_targets)
        from app.agent.edit import unified_diff

        return AgentResult(
            stop_reason=StopReason.RESOLVED if resolved else stop,
            resolved=resolved,
            iterations=iterations,
            usage=usage,
            tool_calls=list(self.executor.tool_calls),
            edits=list(self.executor.edits),
            diff=unified_diff(self.executor.edits),
            plan=plan,
            summary=summary or final_summary,
        )

    def _verify(self, verify_targets: list[str] | None) -> tuple[bool, str]:
        """Authoritative final test run deciding whether the bug is resolved."""
        from app.runner.pytest_runner import NoTestFramework, run_pytest

        try:
            result = run_pytest(
                self.executor.root,
                self.executor.sandbox,
                targets=verify_targets,
                limits=self.executor.limits,
            )
        except NoTestFramework as exc:
            return False, f"verification skipped: {exc}"
        self.executor.last_test_result = result
        verb = "resolved" if result.ok else "unresolved"
        return result.ok, (
            f"{verb}: {result.passed} passed, {result.failed} failed, {result.errors} error(s)"
        )


def _text_of(response: Any) -> str:
    """Concatenate the text blocks of a response."""
    parts = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts).strip()


def _accumulate_usage(usage: TokenUsage, response: Any) -> None:
    u = getattr(response, "usage", None)
    if u is None:
        return
    usage.add(
        int(getattr(u, "input_tokens", 0) or 0),
        int(getattr(u, "output_tokens", 0) or 0),
    )
