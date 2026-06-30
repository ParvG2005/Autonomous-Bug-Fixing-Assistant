"""``bugfix-scan`` — run a proactive scan and (optionally) promote findings.

    bugfix-scan run --repo owner/name --path ./checkout            # dry: just report
    bugfix-scan run --repo owner/name --path ./checkout --confirm  # promote → jobs

Promotion enqueues autonomous fix jobs that **cost tokens**, so — like
``bugfix-eval`` — ``run`` refuses to promote without ``--confirm`` (a stop-and-ask
gate). Without it the scan still records candidates as findings (no spend) so the
dashboard's Findings tab can show them; ``--confirm`` plus ``--max-jobs`` is what
actually files jobs. Reproduction downstream is the precision filter.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from app.core.settings import get_settings
from app.db.session import Database
from app.discovery.service import ScanSummary, run_scan
from app.discovery.sources import DEFAULT_DETECTORS
from app.discovery.sources.base import Detector
from app.discovery.sources.diffs import DiffHotspotDetector
from app.discovery.sources.static import StaticAnalysisDetector
from app.discovery.sources.tests import ExistingTestsDetector
from app.index.clone import clone_repo
from app.models.entities import ScanTrigger
from app.sandbox import get_sandbox

app = typer.Typer(add_completion=False, help="Proactive bug discovery: scan a repo for bugs.")
console = Console()

_DETECTORS: dict[str, Detector] = {
    "tests": ExistingTestsDetector(),
    "static": StaticAnalysisDetector(),
    "diff": DiffHotspotDetector(),
}


def _select_detectors(spec: str | None) -> list[Detector]:
    if not spec:
        return DEFAULT_DETECTORS
    chosen: list[Detector] = []
    for name in (s.strip() for s in spec.split(",")):
        if name not in _DETECTORS:
            console.print(f"[red]unknown source {name!r} (have: {', '.join(_DETECTORS)})[/red]")
            raise typer.Exit(code=2)
        chosen.append(_DETECTORS[name])
    return chosen


@app.command()
def run(
    repo: Annotated[str, typer.Option(help="Registered repo full name, e.g. owner/name")],
    path: Annotated[
        Path | None, typer.Option(help="Local checkout to scan (skips cloning)")
    ] = None,
    sources: Annotated[
        str | None, typer.Option(help="Comma list: tests,static,diff (default: all)")
    ] = None,
    max_jobs: Annotated[int, typer.Option(help="Max findings promoted to jobs")] = 5,
    confirm: Annotated[
        bool, typer.Option(help="Confirm spend — required to PROMOTE findings to jobs")
    ] = False,
) -> None:
    """Scan REPO for latent bugs; with --confirm, promote the top findings to jobs."""
    settings = get_settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL not configured — discovery needs the database.[/red]")
        raise typer.Exit(code=2)

    detectors = _select_detectors(sources)
    if not confirm:
        console.print(
            "[yellow]Promoting findings enqueues autonomous fix jobs that cost tokens.[/yellow]\n"
            "Recording candidates only (no jobs). Re-run with [bold]--confirm[/bold] to promote."
        )

    if path is not None:
        workspace = path.resolve()
        if not workspace.is_dir():
            console.print(f"[red]{workspace} is not a directory[/red]")
            raise typer.Exit(code=2)
    else:
        workspace = (settings.workspace_root / f"scan-{repo.replace('/', '_')}").resolve()
        console.print(f"cloning [bold]{repo}[/bold] → {workspace}")
        clone_repo(f"https://github.com/{repo}.git", workspace, depth=1)

    summary = asyncio.run(
        _run(
            settings_db_url=settings.database_url,
            repo=repo,
            workspace=workspace,
            detectors=detectors,
            max_jobs=max_jobs,
            promote=confirm,
        )
    )
    _print_summary(repo, summary, promoted=confirm)


async def _run(*, settings_db_url: str, repo: str, workspace: Path, detectors: list[Detector],
               max_jobs: int, promote: bool) -> ScanSummary:
    db = Database(settings_db_url)
    try:
        return await run_scan(
            db,
            repo,
            workspace,
            detectors=detectors,
            sandbox=get_sandbox(),
            trigger=ScanTrigger.MANUAL,
            max_jobs=max_jobs,
            promote=promote,
        )
    finally:
        await db.dispose()


def _print_summary(repo: str, s: ScanSummary, *, promoted: bool) -> None:
    console.print(
        f"\n[bold]scan {s.scan_id}[/bold] of {repo} "
        f"(sources: {', '.join(s.sources_run) or 'none'})"
    )
    console.print(f"  candidates : {s.candidates}")
    console.print(f"  duplicates : {s.duplicates} (already known — not refiled)")
    console.print(f"  parked     : {s.parked} (recorded, not promoted)")
    verb = "promoted → jobs" if promoted else "promotable (pass --confirm)"
    console.print(f"  {verb:<26}: {len(s.promoted_job_ids)}")
    for jid in s.promoted_job_ids:
        console.print(f"    • job {jid}")
    if s.errors:
        console.print("[yellow]  detector errors:[/yellow]")
        for src, err in s.errors.items():
            console.print(f"    {src}: {err}")


if __name__ == "__main__":  # pragma: no cover
    app()
