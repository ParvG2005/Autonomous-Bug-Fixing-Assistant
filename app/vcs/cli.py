"""``bugfix-pr`` CLI — the human gate and the draft-PR opener (Phase 5).

    bugfix-pr approve <job_id> --actor you        record an approval
    bugfix-pr reject  <job_id> --actor you        record a rejection
    bugfix-pr status  <job_id>                    show the latest decision
    bugfix-pr open    <job_id> --bundle fix.json  open the DRAFT PR (gated)

Decisions persist to a JSON-lines store (``./.bugfix/approvals.jsonl`` by
default). ``open`` performs the only remote write in the system: it refuses
unless an ``approved`` record exists, mints a short-lived installation token,
and opens a **draft** PR. Opening a real PR is a STOP-AND-ASK action — it
requires ``--confirm`` and configured GitHub App credentials.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from app.vcs.approval import (
    Approval,
    ApprovalError,
    Decision,
    JsonFileApprovalStore,
)
from app.vcs.models import FileChange, FixBundle, RepoRef

app = typer.Typer(add_completion=False, help="Human-gated GitHub draft-PR plane.")
console = Console()

_DEFAULT_STORE = Path("./.bugfix/approvals.jsonl")


@app.callback()
def _main() -> None:
    """Human gate + draft-PR opener (sole remote-write surface)."""


def _store(path: Path) -> JsonFileApprovalStore:
    return JsonFileApprovalStore(path)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@app.command()
def approve(
    job_id: Annotated[str, typer.Argument(help="Job id to approve")],
    actor: Annotated[str, typer.Option(help="Human identity recording the decision")],
    note: Annotated[str, typer.Option(help="Optional note")] = "",
    store: Annotated[Path, typer.Option(help="Approval store path")] = _DEFAULT_STORE,
) -> None:
    """Record an APPROVED decision for JOB_ID."""
    _store(store).record(
        Approval(
            job_id=job_id,
            decision=Decision.APPROVED,
            actor=actor,
            decided_at=_now_iso(),
            note=note,
        )
    )
    console.print(f"[green]approved[/green] job {job_id} by {actor}")


@app.command()
def reject(
    job_id: Annotated[str, typer.Argument(help="Job id to reject")],
    actor: Annotated[str, typer.Option(help="Human identity recording the decision")],
    note: Annotated[str, typer.Option(help="Optional note")] = "",
    store: Annotated[Path, typer.Option(help="Approval store path")] = _DEFAULT_STORE,
) -> None:
    """Record a REJECTED decision for JOB_ID (no remote action ever follows)."""
    _store(store).record(
        Approval(
            job_id=job_id,
            decision=Decision.REJECTED,
            actor=actor,
            decided_at=_now_iso(),
            note=note,
        )
    )
    console.print(f"[yellow]rejected[/yellow] job {job_id} by {actor}")


@app.command()
def status(
    job_id: Annotated[str, typer.Argument(help="Job id to inspect")],
    store: Annotated[Path, typer.Option(help="Approval store path")] = _DEFAULT_STORE,
) -> None:
    """Show the latest decision for JOB_ID."""
    latest = _store(store).latest(job_id)
    if latest is None:
        console.print(f"job {job_id}: [dim]no decision recorded[/dim]")
        raise typer.Exit(code=1)
    color = "green" if latest.decision is Decision.APPROVED else "yellow"
    console.print(
        f"job {job_id}: [{color}]{latest.decision.value}[/{color}] "
        f"by {latest.actor} at {latest.decided_at}"
    )


def _bundle_from_json(path: Path) -> FixBundle:
    raw = json.loads(path.read_text(encoding="utf-8"))
    repo = RepoRef(**raw["repo"])
    changes = [FileChange(**c) for c in raw.get("changes", [])]
    return FixBundle(
        job_id=raw["job_id"],
        repo=repo,
        base_branch=raw["base_branch"],
        head_branch=raw["head_branch"],
        title=raw["title"],
        commit_message=raw["commit_message"],
        body=raw.get("body", ""),
        changes=changes,
        reasoning_comment=raw.get("reasoning_comment", ""),
    )


@app.command()
def open(
    job_id: Annotated[str, typer.Argument(help="Job id (must match the bundle)")],
    bundle: Annotated[Path, typer.Option(help="FixBundle JSON produced for the job")],
    store: Annotated[Path, typer.Option(help="Approval store path")] = _DEFAULT_STORE,
    confirm: Annotated[bool, typer.Option(help="Required to perform the real remote write")] = (
        False
    ),
) -> None:
    """Open the human-approved DRAFT PR for JOB_ID (the only remote write)."""
    from app.core.settings import get_settings
    from app.vcs.auth import settings_token_minter
    from app.vcs.publish import open_draft_pr_for_fix

    fix = _bundle_from_json(bundle)
    if fix.job_id != job_id:
        console.print(f"[red]bundle job_id {fix.job_id!r} != {job_id!r}[/red]")
        raise typer.Exit(code=2)

    if not confirm:
        console.print(
            "[yellow]This opens a real draft PR on GitHub.[/yellow] "
            "Re-run with [bold]--confirm[/bold] once the job is approved."
        )
        raise typer.Exit(code=2)

    settings = get_settings()
    # `now` from the wall clock; auth backdates iat for skew tolerance.
    minter = settings_token_minter(settings, now=int(datetime.now(UTC).timestamp()))
    try:
        pr = open_draft_pr_for_fix(fix, store=_store(store), token_minter=minter)
    except ApprovalError as exc:
        console.print(f"[red]refused:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]draft PR opened[/green] #{pr.number}: {pr.url}")


if __name__ == "__main__":
    app()
