"""``bugfix-eval`` CLI — run the eval and print the headline resolve rate.

    bugfix-eval list                          list cases in a suite
    bugfix-eval run --suite custom --confirm  run the suite, print resolve rate

A real run drives the agent against the live Anthropic API and **costs tokens** —
the build plan lists it as a stop-and-ask gate, so ``run`` refuses without
``--confirm``. ``--compare PATH`` diffs this run's metrics against a saved report
(the tuning loop); ``--out PATH`` saves this run so the *next* one can compare.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from app.agent.client import make_create_message
from app.agent.models import AgentBudget
from app.core.settings import get_settings
from app.sandbox import LocalSandbox, ResourceLimits, get_sandbox
from eval.dataset import CUSTOM_SUITE, load_suite
from eval.harness import CaseResult, run_suite
from eval.score import build_report, load_report, save_report, score_delta
from eval.swebench import SWEBENCH_LITE_SUITE, load_swebench_lite

app = typer.Typer(add_completion=False, help="Eval harness: run cases and score resolve rate.")
console = Console()


def _load_cases(suite: str, jsonl: Path | None, limit: int | None):  # type: ignore[no-untyped-def]
    if suite == SWEBENCH_LITE_SUITE:
        if jsonl is None:
            console.print("[red]--jsonl is required for the swebench-lite suite[/red]")
            raise typer.Exit(code=2)
        return load_swebench_lite(jsonl, limit=limit)
    cases = load_suite(suite)
    return cases[:limit] if limit is not None else cases


@app.command(name="list")
def list_cases(
    suite: Annotated[str, typer.Option(help="Suite name")] = CUSTOM_SUITE,
) -> None:
    """List the cases in SUITE."""
    cases = load_suite(suite)
    table = Table(title=f"eval suite: {suite}")
    table.add_column("id")
    table.add_column("language")
    table.add_column("title")
    for c in cases:
        table.add_row(c.id, c.language, c.title or "")
    console.print(table)


@app.command()
def run(
    suite: Annotated[str, typer.Option(help="Suite name")] = CUSTOM_SUITE,
    model: Annotated[str | None, typer.Option(help="Model id (default: settings)")] = None,
    label: Annotated[str, typer.Option(help="Label this run (for saved reports)")] = "",
    limit: Annotated[int | None, typer.Option(help="Run at most N cases")] = None,
    jsonl: Annotated[Path | None, typer.Option(help="SWE-bench-lite JSONL path")] = None,
    local: Annotated[bool, typer.Option(help="Force the local subprocess sandbox")] = True,
    max_iterations: Annotated[int, typer.Option(help="Agent iteration budget per case")] = 16,
    deadline: Annotated[float, typer.Option(help="Per-case wall-clock cap (seconds)")] = 360.0,
    timeout: Annotated[float, typer.Option(help="Per-test-run cap (seconds)")] = 120.0,
    out: Annotated[Path | None, typer.Option(help="Save the scored report JSON here")] = None,
    compare: Annotated[Path | None, typer.Option(help="Diff against a saved report")] = None,
    confirm: Annotated[bool, typer.Option(help="Confirm spend — required for a real run")] = False,
) -> None:
    """Run SUITE end-to-end and print the headline resolve rate.

    Costs tokens: pass --confirm to acknowledge the spend (stop-and-ask gate).
    """
    settings = get_settings()
    if settings.anthropic_api_key is None:
        console.print("[red]ANTHROPIC_API_KEY not set — cannot run the eval.[/red]")
        raise typer.Exit(code=2)
    if not confirm:
        console.print(
            "[yellow]A real eval run costs tokens (live Anthropic API per case).[/yellow]\n"
            "Re-run with [bold]--confirm[/bold] to acknowledge the spend."
        )
        raise typer.Exit(code=2)

    model_id = model or settings.agent_model
    cases = _load_cases(suite, jsonl, limit)
    console.print(
        f"running [bold]{len(cases)}[/bold] case(s) from [bold]{suite}[/bold] ({model_id})"
    )

    sandbox = LocalSandbox() if local else get_sandbox()
    budget = AgentBudget(max_iterations=max_iterations, deadline_s=deadline)
    limits = ResourceLimits(timeout_s=timeout)

    def _progress(r: CaseResult) -> None:
        mark = "[green]✓[/green]" if r.resolved else "[red]✗[/red]"
        extra = f" [red]{r.error}[/red]" if r.error else ""
        console.print(f"  {mark} {r.case_id}  ({r.duration_s:.1f}s, ${r.cost_usd:.4f}){extra}")

    results = run_suite(
        cases,
        make_create_message(settings),
        model=model_id,
        progress=_progress,
        sandbox=sandbox,
        budget=budget,
        limits=limits,
    )

    report = build_report(suite, model_id, results, label=label)
    _print_report(report)

    if compare is not None:
        prev = load_report(compare)
        delta = score_delta(prev["metrics"], report.metrics)
        _print_delta(prev.get("label") or compare.name, delta)

    if out is not None:
        save_report(report, out)
        console.print(f"saved report → {out}")


def _print_report(report) -> None:  # type: ignore[no-untyped-def]
    m = report.metrics
    table = Table(title=f"{report.suite} @ {report.model}")
    table.add_column("metric")
    table.add_column("value", justify="right")
    table.add_row("resolve rate", f"{m.resolve_rate:.1%}")
    table.add_row("resolved", f"{m.resolved}/{m.total}")
    table.add_row("regression rate", f"{m.regression_rate:.1%}")
    table.add_row("mean time-to-fix", f"{m.mean_time_to_fix_s:.1f}s")
    table.add_row("cost per fix", f"${m.cost_per_fix_usd:.4f}")
    table.add_row("total spend", f"${m.total_cost_usd:.4f}")
    console.print(table)
    console.print(f"[bold green]HEADLINE:[/bold green] {report.headline()}")


def _print_delta(baseline: str, delta: dict[str, dict[str, float]]) -> None:
    table = Table(title=f"delta vs {baseline}")
    table.add_column("metric")
    table.add_column("before", justify="right")
    table.add_column("after", justify="right")
    table.add_column("Δ", justify="right")
    for key, d in delta.items():
        arrow = "[green]↑[/green]" if d["improved"] else "[red]↓[/red]"
        sign = "+" if d["delta"] >= 0 else ""
        moved = f"{arrow} {sign}{d['delta']:.4f}"
        table.add_row(key, f"{d['before']:.4f}", f"{d['after']:.4f}", moved)
    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    app()
