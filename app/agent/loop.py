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

# How many times to push back when the model ends its turn without editing.
# Small so a model that genuinely has nothing to do still terminates quickly.
_MAX_CONTINUE_NUDGES = 2
_CONTINUE_NUDGE = (
    "You ended your turn without making any edits, but the target test still "
    "fails. Do not just describe the fix — apply it: use edit_file to change the "
    "source, then run_tests to verify. If you are certain no source change can "
    "fix this, say so explicitly and explain why."
)


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

        # Pre-flight: if the repro test can't even be collected because the repo
        # isn't importable in the sandbox, there is no failing-test signal to work
        # against. Abort before spending any model calls, with an actionable reason,
        # rather than flailing to max_iterations.
        unimportable = self._preflight_unimportable(verify_targets)
        if unimportable is not None:
            from app.agent.edit import unified_diff

            return AgentResult(
                stop_reason=StopReason.UNREPRODUCIBLE,
                resolved=False,
                iterations=0,
                usage=usage,
                tool_calls=list(self.executor.tool_calls),
                edits=[],
                diff=unified_diff([]),
                plan="",
                summary=unimportable,
            )

        plan = self.plan(task, usage) if do_plan else ""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": build_task_prompt(task, plan)}
        ]

        stop = StopReason.MAX_ITERATIONS
        summary = ""
        iterations = 0
        nudges = 0

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
                # The model ended its turn. If it has not edited anything, it
                # likely narrated a plan instead of executing it (a known failure
                # mode, worsened by the planning step). Push back and let it act,
                # bounded by ``_MAX_CONTINUE_NUDGES`` so a model with nothing to
                # do still terminates.
                if not self.executor.edits and nudges < _MAX_CONTINUE_NUDGES:
                    nudges += 1
                    messages.append({"role": "user", "content": _CONTINUE_NUDGE})
                    continue
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

    def _preflight_unimportable(self, verify_targets: list[str] | None) -> str | None:
        """Return a diagnostic if the repro test can't be collected (import error).

        Runs the target test(s) once against the untouched repo. A collection
        error whose cause is a missing module means the repo isn't importable in
        the sandbox — an environment problem the agent can't edit its way out of.
        Returns ``None`` (proceed normally) for a genuine failing test, no tests,
        or any non-import error.
        """
        from app.runner.models import Outcome
        from app.runner.pytest_runner import NoTestFramework, run_pytest

        try:
            result = run_pytest(
                self.executor.root,
                self.executor.sandbox,
                targets=verify_targets,
                limits=self.executor.limits,
            )
        except NoTestFramework:
            return None
        if result.outcome is not Outcome.ERROR:
            return None
        blob = f"{result.stdout}\n{result.stderr}"
        for failure in result.failures:
            blob += f"\n{failure.message}"
        marker = next((m for m in ("ModuleNotFoundError", "ImportError") if m in blob), None)
        if marker is None:
            return None
        line = next((ln.strip() for ln in blob.splitlines() if marker in ln), marker)
        return (
            f"reproduction test could not be collected — repo not importable in the sandbox "
            f"({line})"
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
