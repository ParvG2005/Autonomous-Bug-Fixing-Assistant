"""``bugfix-agent`` CLI — exercise the agent loop (Phase 3) and pipeline (Phase 4).

    bugfix-agent fix   <workspace> --task "..."     diagnose + fix a bug, print the diff
    bugfix-agent solve <workspace> --issue "..."    issue → verified patch + writeup

``fix`` is the Phase 3 surface (failing test → green). ``solve`` is the Phase 4
core milestone: raw issue text (or ``--issue-file``) → localize → reproduce → fix
→ a Markdown reasoning writeup. ``--local`` forces the subprocess sandbox (no
Docker); ``--target`` (on ``fix``) restricts the verification run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from app.agent.client import MissingAPIKey, make_create_message
from app.agent.loop import AgentLoop
from app.agent.models import AgentBudget
from app.core.settings import get_settings
from app.index.repo_brain import RepoBrain
from app.sandbox import ResourceLimits, get_sandbox

app = typer.Typer(add_completion=False, help="Autonomous bug-fixing agent loop.")
console = Console()


@app.callback()
def _main() -> None:
    """Autonomous bug-fixing agent loop (use the `fix` subcommand)."""


@app.command()
def fix(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory")],
    task: Annotated[str, typer.Option(help="What to fix (issue text / failing test)")],
    target: Annotated[list[str] | None, typer.Option(help="Verification test target(s)")] = None,
    local: Annotated[bool, typer.Option(help="Force the local subprocess sandbox")] = False,
    max_iterations: Annotated[int, typer.Option(help="Model-turn budget")] = 20,
    timeout: Annotated[float, typer.Option(help="Wall-clock budget (seconds)")] = 600.0,
    no_plan: Annotated[bool, typer.Option(help="Skip the planning step")] = False,
) -> None:
    """Run the agent loop against WORKSPACE and print the resulting diff."""
    settings = get_settings()
    try:
        create_message = make_create_message(settings)
    except MissingAPIKey as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    brain = RepoBrain(workspace)
    sandbox = get_sandbox(settings, prefer_local=local)
    from app.agent.tools import ToolExecutor

    executor = ToolExecutor(workspace, brain, sandbox, limits=ResourceLimits(timeout_s=timeout))
    loop = AgentLoop(
        executor,
        create_message,
        model=settings.agent_model,
        budget=AgentBudget(max_iterations=max_iterations, deadline_s=timeout),
    )

    result = loop.run(task, verify_targets=target, do_plan=not no_plan)

    if result.plan:
        console.print("[bold]Plan[/bold]")
        console.print(result.plan)
    console.print(
        f"\n[dim]{len(result.tool_calls)} tool calls, {result.iterations} turns, "
        f"{result.usage.total} tokens[/dim]"
    )
    if result.diff:
        console.print("\n[bold]Diff[/bold]")
        console.print(result.diff)
    if result.summary:
        console.print(f"\n{result.summary}")

    if result.resolved:
        console.print("\n[bold green]RESOLVED[/bold green] — target tests pass")
    else:
        console.print(f"\n[bold red]UNRESOLVED[/bold red] ({result.stop_reason.value})")
        raise typer.Exit(code=1)


@app.command()
def solve(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory")],
    issue: Annotated[str | None, typer.Option(help="Issue text / stack trace")] = None,
    issue_file: Annotated[Path | None, typer.Option(help="Read the issue from a file")] = None,
    writeup_out: Annotated[Path | None, typer.Option(help="Write the writeup here")] = None,
    local: Annotated[bool, typer.Option(help="Force the local subprocess sandbox")] = False,
    max_iterations: Annotated[int, typer.Option(help="Model-turn budget")] = 20,
    timeout: Annotated[float, typer.Option(help="Wall-clock budget (seconds)")] = 600.0,
    no_plan: Annotated[bool, typer.Option(help="Skip the planning step")] = False,
) -> None:
    """Phase 4: solve an issue end to end and print the diff + reasoning writeup."""
    if issue_file is not None:
        issue_text = issue_file.read_text(encoding="utf-8")
    elif issue is not None:
        issue_text = issue
    else:
        console.print("[red]provide --issue or --issue-file[/red]")
        raise typer.Exit(code=2)

    settings = get_settings()
    try:
        create_message = make_create_message(settings)
    except MissingAPIKey as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    from app.agent.solve import solve_issue

    sandbox = get_sandbox(settings, prefer_local=local)
    result = solve_issue(
        workspace,
        issue_text,
        create_message,
        model=settings.agent_model,
        sandbox=sandbox,
        budget=AgentBudget(max_iterations=max_iterations, deadline_s=timeout),
        limits=ResourceLimits(timeout_s=timeout),
        do_plan=not no_plan,
    )

    if result.suspects:
        console.print("[bold]Suspect files[/bold]")
        for suspect in result.suspects[:5]:
            console.print(f"  {suspect.path}  (score {suspect.score:g})")
    if result.flags:
        console.print("\n[bold yellow]Guardrail flags[/bold yellow]")
        for flag in result.flags:
            console.print(f"  {flag}")
    if result.agent.diff:
        console.print("\n[bold]Diff[/bold]")
        console.print(result.agent.diff)

    if writeup_out is not None:
        writeup_out.write_text(result.writeup, encoding="utf-8")
        console.print(f"\n[dim]writeup → {writeup_out}[/dim]")
    else:
        console.print("\n[bold]Writeup[/bold]")
        console.print(result.writeup)

    if result.resolved:
        console.print("\n[bold green]RESOLVED[/bold green] — verified patch produced")
    else:
        console.print(f"\n[bold red]UNRESOLVED[/bold red] ({result.agent.stop_reason.value})")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
