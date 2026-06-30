"""``bugfix-run`` CLI — exercise the Phase 2 test runner.

    bugfix-run detect <workspace>          report the detected test framework
    bugfix-run test   <workspace> [paths]  run tests in a sandbox, print results

This is the acceptance surface for Phase 2: ``test`` on a known-failing repo
prints structured pass/fail counts and ``{file, line, function}`` frames per
failure. ``--local`` forces the subprocess fallback (no Docker required).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from app.runner.detect import detect_framework
from app.runner.models import Outcome
from app.runner.pytest_runner import NoTestFramework, run_pytest
from app.sandbox import ResourceLimits, get_sandbox

app = typer.Typer(add_completion=False, help="Test runner: detect and run tests in a sandbox.")
console = Console()

_OUTCOME_STYLE = {
    Outcome.PASSED: "green",
    Outcome.FAILED: "red",
    Outcome.ERROR: "red",
    Outcome.NO_TESTS: "yellow",
    Outcome.TIMEOUT: "red",
}


@app.command()
def detect(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory")],
) -> None:
    """Report the test framework detected in WORKSPACE."""
    framework = detect_framework(workspace)
    if framework is None:
        console.print("[yellow]no supported test framework detected[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"[green]{framework.value}[/green]")


@app.command()
def test(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory")],
    paths: Annotated[list[str] | None, typer.Argument(help="Test targets")] = None,
    local: Annotated[bool, typer.Option(help="Force the local subprocess sandbox")] = False,
    timeout: Annotated[float, typer.Option(help="Wall-clock cap (seconds)")] = 120.0,
) -> None:
    """Run the workspace's tests in a sandbox and print structured results."""
    sandbox = get_sandbox(prefer_local=local)
    limits = ResourceLimits(timeout_s=timeout)
    try:
        result = run_pytest(workspace, sandbox, targets=paths, limits=limits)
    except NoTestFramework as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    style = _OUTCOME_STYLE.get(result.outcome, "white")
    console.print(
        f"[bold {style}]{result.outcome.value.upper()}[/bold {style}]  "
        f"{result.passed} passed, {result.failed} failed, "
        f"{result.errors} error(s), {result.skipped} skipped  "
        f"[dim]({result.duration_s:.2f}s)[/dim]"
    )

    for failure in result.failures:
        console.print(f"\n[bold red]FAIL[/bold red] {failure.nodeid}")
        if failure.message:
            console.print(f"  [red]{failure.message}[/red]")
        for frame in failure.frames:
            console.print(f"    {frame}")

    if not result.ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
