"""Phase 4 orchestrator: issue → reproduce → localize → fix → explain.

:func:`solve_issue` is the core-milestone entrypoint. It turns raw issue text
into a verified patch and a reasoning writeup:

1. **Parse** the issue/stacktrace into an :class:`~app.agent.issue.IssueTask`.
2. **Localize** suspect files from the traceback, referenced paths, and symbols.
3. **Run the agent loop**, seeded with the issue + ranked suspects, instructed to
   reproduce with a failing test (writing one if none exists) and fix the source.
   Edits pass the guardrails (sensitive-file flagging, diff-size cap). When the
   issue names a test, that scopes the authoritative final verification.
4. **Explain**: assemble the Markdown writeup and the change summary.

The model client is injected (as in :class:`~app.agent.loop.AgentLoop`), so the
whole pipeline runs offline against a scripted fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agent.guardrails import DEFAULT_MAX_DIFF_LINES
from app.agent.issue import IssueTask, parse_issue
from app.agent.localize import Suspect, rank_suspects
from app.agent.loop import AgentLoop, CreateMessage
from app.agent.models import AgentBudget, AgentResult
from app.agent.prompts import build_solve_prompt
from app.agent.tools import ToolExecutor
from app.agent.writeup import ChangeSummary, build_writeup, change_summary
from app.core.allowlist import Allowlist
from app.index.repo_brain import RepoBrain
from app.sandbox.base import Sandbox
from app.sandbox.models import ResourceLimits


@dataclass
class SolveResult:
    """Everything Phase 4 produces for one issue."""

    task: IssueTask
    suspects: list[Suspect]
    agent: AgentResult
    flags: list[str]
    writeup: str
    summary: ChangeSummary

    @property
    def resolved(self) -> bool:
        return self.agent.resolved


def solve_issue(
    workspace: Path,
    issue_text: str,
    create_message: CreateMessage,
    *,
    model: str,
    title: str | None = None,
    sandbox: Sandbox | None = None,
    allowlist: Allowlist | None = None,
    budget: AgentBudget | None = None,
    limits: ResourceLimits | None = None,
    max_diff_lines: int = DEFAULT_MAX_DIFF_LINES,
    do_plan: bool = True,
) -> SolveResult:
    """Solve the bug described by ``issue_text`` in ``workspace`` end to end.

    When ``sandbox`` is omitted, a real sandbox is selected from settings (Docker
    when present); tests inject a :class:`~app.sandbox.local.LocalSandbox`.
    """
    brain = RepoBrain(workspace)
    task = parse_issue(issue_text, title=title)
    suspects = rank_suspects(brain, task)

    if sandbox is None:
        from app.core.settings import get_settings
        from app.runner.adapters import detect_adapter
        from app.sandbox import get_sandbox

        # Select the sandbox image carrying the detected language's toolchain
        # (Phase 8). The local fallback ignores the image and runs in-place.
        adapter = detect_adapter(workspace)
        image = adapter.image if adapter is not None else None
        sandbox = get_sandbox(get_settings(), image=image)

    executor = ToolExecutor(
        workspace,
        brain,
        sandbox,
        allowlist=allowlist,
        limits=limits,
        max_diff_lines=max_diff_lines,
    )
    loop = AgentLoop(executor, create_message, model=model, budget=budget)

    # A named test in the issue scopes the authoritative verification; otherwise
    # the whole suite runs (so a freshly written reproduction test is included).
    verify_targets = task.test_nodeids or None
    agent_result = loop.run(
        build_solve_prompt(task, suspects),
        verify_targets=verify_targets,
        do_plan=do_plan,
    )

    flags = list(executor.flags)
    writeup = build_writeup(task, suspects, agent_result, flags=flags)
    summary = change_summary(agent_result.edits)
    return SolveResult(
        task=task,
        suspects=suspects,
        agent=agent_result,
        flags=flags,
        writeup=writeup,
        summary=summary,
    )
